from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from datetime import datetime, timezone
import time
from pathlib import Path
from typing import Dict, Optional

from fastapi import FastAPI, HTTPException
import threading
from concurrent.futures import ThreadPoolExecutor

# Allow running both as a package module and as a direct script.
try:
    from .models import (
        ApproveRequest,
        SendPromptRequest,
        StartRequest,
        StateResponse,
        WebhookStateChange,
        TailLinesRequest,
        RemoteBootstrapRequest,
        RemoteBootstrapResponse,
        RemoteBootstrapWatcher,
        RemoteBootstrapChecks,
    )
    from .state import (
        Session,
        SentinelState,
        PendingAutoHook,
        can_approve,
        can_send_prompt,
        transition_on_approve,
        transition_on_destroy,
        transition_on_send_prompt,
        transition_on_start,
        normalize_observation,
        apply_observation,
        transition_on_human_input,
        maybe_mark_human_idle,
        public_state,
        AUTOMATION_COOLDOWN_SECONDS,
    )
except ImportError:  # pragma: no cover
    from models import (  # type: ignore
        ApproveRequest,
        SendPromptRequest,
        StartRequest,
        StateResponse,
        WebhookStateChange,
        TailLinesRequest,
        RemoteBootstrapRequest,
        RemoteBootstrapResponse,
        RemoteBootstrapWatcher,
        RemoteBootstrapChecks,
    )
    from state import (  # type: ignore
        Session,
        SentinelState,
        PendingAutoHook,
        can_approve,
        can_send_prompt,
        transition_on_approve,
        transition_on_destroy,
        transition_on_send_prompt,
        transition_on_start,
        normalize_observation,
        apply_observation,
        transition_on_human_input,
        maybe_mark_human_idle,
        public_state,
        AUTOMATION_COOLDOWN_SECONDS,
    )

APP_HOST = os.environ.get("CODELEADER_SENTINEL_HOST", os.environ.get("SENTINEL_HOST", "127.0.0.1"))
APP_PORT = int(os.environ.get("CODELEADER_SENTINEL_PORT", os.environ.get("SENTINEL_PORT", "8787")))
OPENCLAW_SESSION_ID = os.environ.get("CODELEADER_OPENCLAW_SESSION_ID", "").strip()
RUN_ID = os.environ.get("CODELEADER_RUN_ID", "").strip()
RUN_DIR_ENV = os.environ.get("CODELEADER_RUN_DIR", "").strip()

# Phase-2 (minimal): shell out to system ssh to drive remote zellij actions.
# Keep defaults conservative; allow override via env.
REMOTE_SSH_HOST = os.environ.get("CODELEADER_REMOTE_SSH_HOST", "").strip()
REMOTE_HOME = os.environ.get("CODELEADER_REMOTE_HOME", "").strip()
REMOTE_SERVICE_ROOT = os.environ.get("CODELEADER_REMOTE_SERVICE_ROOT", (f"{REMOTE_HOME}/.codeleader" if REMOTE_HOME else "")).strip()
REMOTE_ZELLIJ_SESSION = os.environ.get("CODELEADER_REMOTE_ZELLIJ_SESSION", "CodeLeader")
# Only allow read-only-ish commands during experimentation.
ALLOW_REMOTE_EXEC = os.environ.get("CODELEADER_ALLOW_REMOTE_EXEC", "0") in {"1", "true", "TRUE", "yes", "YES"}

# Remote bootstrap (deploy watcher / create venv) is a separate, stricter gate.
# Default: OFF (read-only actions still allowed).
ALLOW_REMOTE_BOOTSTRAP = os.environ.get("CODELEADER_ALLOW_REMOTE_BOOTSTRAP", "0") in {
    "1",
    "true",
    "TRUE",
    "yes",
    "YES",
}
# Optional audit mode: when enabled, log PROMPT_READY heartbeats even when state doesn't change.
# Default keeps logs compact (legacy behavior).
HUMAN_HOOK_CMD = os.environ.get("CODELEADER_HUMAN_HOOK_CMD", "").strip()
HUMAN_HOOK_TIMEOUT_SECONDS = int(os.environ.get("CODELEADER_HUMAN_HOOK_TIMEOUT_SECONDS", "10"))
OPENCLAW_AGENT_TIMEOUT_SECONDS = int(os.environ.get("CODELEADER_OPENCLAW_AGENT_TIMEOUT_SECONDS", "90"))
NOTIFY_CMD = os.environ.get("CODELEADER_NOTIFY_CMD", "").strip()
NOTIFY_PREFIX = os.environ.get("CODELEADER_NOTIFY_PREFIX", "[CodeLeader Notify] ")
NOTIFY_TIMEOUT_SECONDS = int((os.environ.get("CODELEADER_NOTIFY_TIMEOUT_SECONDS") or "120").strip())

LOG_PROMPT_READY_HEARTBEAT = os.environ.get("CODELEADER_LOG_PROMPT_READY_HEARTBEAT", "0") in {
    "1",
    "true",
    "TRUE",
    "yes",
    "YES",
}

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "runtime"
RUNS_DIR = RUNTIME_DIR / "runs"
RUN_DIR = Path(RUN_DIR_ENV) if RUN_DIR_ENV else (RUNS_DIR / RUN_ID if RUN_ID else RUNTIME_DIR)
EVENTS_LOG = RUN_DIR / "events.log"
CURRENT_JSON = RUNTIME_DIR / "current.json"

RUN_DIR.mkdir(parents=True, exist_ok=True)
RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

GATEWAY_EVENT_HUMAN_INTERVENTION_STARTED = "HUMAN_INTERVENTION_STARTED"
GATEWAY_EVENT_AUTO_FLOW_COMPLETED = "AUTO_FLOW_COMPLETED"
GATEWAY_EVENT_AUTO_FLOW_BLOCKED_ON_APPROVAL = "AUTO_FLOW_BLOCKED_ON_APPROVAL"
GATEWAY_EVENT_HUMAN_INTERVENTION_READY_FOR_HOOK = "HUMAN_INTERVENTION_READY_FOR_HOOK"


def _clear_all_pending_auto_hooks(session: Session, reason: str) -> None:
    if session.pending_auto_hooks:
        append_event(
            {
                "type": "AUTO_HOOK_BUFFER_CLEARED",
                "session_id": session.session_id,
                "count": len(session.pending_auto_hooks),
                "reason": reason,
            }
        )
    session.pending_auto_hooks.clear()


def _enqueue_auto_hook(session: Session, event_type: str, default_tail_text: str) -> None:
    session.auto_hook_seq += 1
    hook = PendingAutoHook(
        hook_id=f"{session.session_id}:autohook:{session.auto_hook_seq}",
        event_type=event_type,
        default_tail_text=default_tail_text,
        due_ts=time.time() + 5,
    )
    session.pending_auto_hooks.append(hook)
    append_event(
        {
            "type": "AUTO_HOOK_BUFFERED",
            "session_id": session.session_id,
            "hook_id": hook.hook_id,
            "event_type": event_type,
            "due_in_seconds": 5,
        }
    )


def _flush_due_auto_hooks(session: Session) -> None:
    if not session.pending_auto_hooks:
        return
    now = time.time()
    due_hooks = [hook for hook in session.pending_auto_hooks if hook.due_ts <= now]
    if not due_hooks:
        return
    session.pending_auto_hooks = [hook for hook in session.pending_auto_hooks if hook.due_ts > now]
    for hook in due_hooks:
        if session.pending_approval is not None:
            event_type = GATEWAY_EVENT_AUTO_FLOW_BLOCKED_ON_APPROVAL
        elif session.state == SentinelState.WAITING_FOR_PROMPT:
            last_working = session.last_working_observed_ts
            last_ready = session.last_ready_observed_ts
            if last_working is not None and (now - last_working) < 3:
                append_event(
                    {
                        "type": "AUTO_HOOK_DROPPED",
                        "session_id": session.session_id,
                        "hook_id": hook.hook_id,
                        "original_event_type": hook.event_type,
                        "reason": "recent_working_observation_before_completed_flush",
                    }
                )
                continue
            if last_working is not None and last_ready is not None and last_working > last_ready:
                append_event(
                    {
                        "type": "AUTO_HOOK_DROPPED",
                        "session_id": session.session_id,
                        "hook_id": hook.hook_id,
                        "original_event_type": hook.event_type,
                        "reason": "working_observation_newer_than_ready_observation",
                    }
                )
                continue
            event_type = GATEWAY_EVENT_AUTO_FLOW_COMPLETED
        else:
            append_event(
                {
                    "type": "AUTO_HOOK_DROPPED",
                    "session_id": session.session_id,
                    "hook_id": hook.hook_id,
                    "original_event_type": hook.event_type,
                    "reason": f"state_reconciled_to_{session.state.value.lower()}_before_flush",
                }
            )
            continue
        _emit_gateway_hook(
            session=session,
            event_type=event_type,
            default_tail_text=hook.default_tail_text,
            include_default_tail=True,
        )


def _sync_human_idle(session: Session) -> None:
    if maybe_mark_human_idle(session, time.time()):
        append_event(
            {
                "type": "HUMAN_INPUT_IDLE",
                "session_id": session.session_id,
                "state": session.state.value,
                "control_state": session.control_state,
                "reason": session.human_reason,
            }
        )


def _bootstrap_active(session: Session) -> bool:
    if not session.bootstrap_phase:
        return True
    if (time.time() - session.bootstrap_started_ts) >= 8:
        session.bootstrap_phase = False
        append_event(
            {
                "type": "BOOTSTRAP_PHASE_EXITED",
                "session_id": session.session_id,
                "reason": "time_grace_elapsed",
            }
        )
        return True
    return False


def _tail_looks_like_welcome_idle(default_tail_text: str) -> bool:
    if not default_tail_text:
        return True
    t = default_tail_text
    return (
        "Welcome back!" in t
        and "Recent activity" in t
        and (
            "Try \"edit <filepath> to...\"" in t
            or "Try \"refactor <filepath>\"" in t
            or "Try \"write a test for <filepath>\"" in t
            or "Try \"fix typecheck errors\"" in t
        )
    )


def _build_gateway_hook_payload(
    *,
    session: Session,
    event_type: str,
    default_tail_text: str | None = None,
    include_default_tail: bool = False,
) -> dict:
    payload_reason = None if event_type in {
        GATEWAY_EVENT_AUTO_FLOW_COMPLETED,
        GATEWAY_EVENT_AUTO_FLOW_BLOCKED_ON_APPROVAL,
    } else session.human_reason
    payload = {
        "event_type": event_type,
        "session_id": session.session_id,
        "semantic_state": public_state(session).value,
        "control_state": session.control_state,
        "automation_blocked": session.automation_blocked,
        "reason": payload_reason,
        "blocked_reason": session.blocked_reason,
        "ts": _ts(),
        "debug_hints": {
            "context_fetch_examples": ["tail_lines_30", "tail_lines_60", "tail_lines_120"],
            "authority": "sentinel",
            "note": "If current context is insufficient, request more tail context from sentinel using tail_lines_<N>. N is flexible; recommended examples: 30, 60, 120.",
            "api": {
                "method": "POST",
                "path": "/api/v1/context/read_tail_lines",
                "body_template": {
                    "session_id": session.session_id,
                    "lines": 60
                },
                "body_rule": "Use the current session_id from this payload, and replace lines with any positive integer you need. Example aliases: tail_lines_30, tail_lines_60, tail_lines_120."
            }
        },
    }
    if session.pending_approval is not None:
        payload["pending_approval"] = {
            "approval_id": session.pending_approval.approval_id,
            "reason": session.pending_approval.reason,
            "created_ts": session.pending_approval.created_ts,
        }
    if include_default_tail:
        payload["default_tail_text"] = default_tail_text or ""
    return payload


def _format_hook_message(payload: dict) -> str:
    event_type = payload.get("event_type", "UNKNOWN")
    session_id = payload.get("session_id", "unknown")
    state = payload.get("semantic_state") or "none"
    control_state = payload.get("control_state") or "none"
    automation_blocked = payload.get("automation_blocked")
    reason = payload.get("reason") or "none"
    blocked_reason = payload.get("blocked_reason") or "none"
    default_tail_text = payload.get("default_tail_text", "") or ""
    hints = payload.get("debug_hints", {}) or {}
    examples = hints.get("context_fetch_examples", []) or []
    api = hints.get("api", {}) or {}

    if event_type == GATEWAY_EVENT_HUMAN_INTERVENTION_STARTED:
        return (
            "[CodeLeader Hook]\n"
            f"Type: {event_type}\n"
            f"Session: {session_id}\n\n"
            "Stop now.\n"
            "Human intervention has started.\n"
            "Do not send any new prompt.\n"
            "Wait for the next hook."
        )

    lines = [
        "[CodeLeader Hook]",
        f"Type: {event_type}",
        f"Session: {session_id}",
        f"State: {state}",
        f"Control: {control_state}",
        f"AutomationBlocked: {str(automation_blocked).lower()}",
    ]
    if reason != "none":
        lines.append(f"Reason: {reason}")
    if blocked_reason != "none":
        lines.append(f"BlockedReason: {blocked_reason}")
    lines.append("")

    if event_type == GATEWAY_EVENT_HUMAN_INTERVENTION_READY_FOR_HOOK:
        lines += [
            "Human intervention appears finished.",
            "Do not rush to send a new prompt.",
            "First inspect the current tail context.",
            "If it is not enough, strongly prefer requesting more context first (for example: tail_lines_30 or tail_lines_60).",
        ]
    elif event_type == GATEWAY_EVENT_AUTO_FLOW_COMPLETED:
        lines += [
            "The remote round appears complete.",
            "Inspect the returned result first.",
            "If you decide to continue, send exactly one new prompt.",
            "After sending it, stop immediately and wait for the next hook.",
        ]
    elif event_type == GATEWAY_EVENT_AUTO_FLOW_BLOCKED_ON_APPROVAL:
        profile = _approval_profile(blocked_reason if blocked_reason != "none" else None)
        allowed = profile["allowed"]
        decision_line = " / ".join(allowed)
        lines += [
            "The remote flow is blocked on approval.",
            "Do not send any prompt now.",
            "If the current tail context is insufficient, request more context first.",
            f"Otherwise choose exactly one decision: {decision_line}.",
            "",
            "Allowed decisions:",
            "- yes = approve once",
        ]
        if "always" in allowed:
            lines.append("- always = approve and persist allow for this project scope")
        lines.append("- no = reject and do not continue")

    if default_tail_text:
        lines += ["", "Default tail context:", default_tail_text]

    if examples:
        lines += [
            "",
            "Context fetch hints:",
            "- If current context is insufficient, request more tail context yourself.",
            "- Example requests: tail_lines_30, tail_lines_60, tail_lines_120",
            "- Do not wait for additional context to arrive automatically.",
        ]

    if api:
        lines += [
            "",
            "Sentinel context API:",
            f"- {api.get('method', 'POST')} {api.get('path', '/api/v1/context/read_tail_lines')}",
            f"- body_template: {json.dumps(api.get('body_template', {}), ensure_ascii=False)}",
            f"- body_rule: {api.get('body_rule', '')}",
        ]

    if event_type in {GATEWAY_EVENT_HUMAN_INTERVENTION_READY_FOR_HOOK, GATEWAY_EVENT_AUTO_FLOW_COMPLETED}:
        lines += [
            "",
            "Sent prompt API:",
            f"- POST /api/v1/action/send_prompt?session_id={session_id}",
            '- body_template: {"prompt":"<your next prompt>"}',
            "- rule: send at most one prompt, then stop and wait for the next hook",
        ]
    elif event_type == GATEWAY_EVENT_AUTO_FLOW_BLOCKED_ON_APPROVAL:
        profile = _approval_profile(blocked_reason if blocked_reason != "none" else None)
        allowed = profile["allowed"]
        lines += [
            "",
            "Approval API:",
            f"- POST /api/v1/action/approve?session_id={session_id}",
            '- body_template: {"decision":"yes"}',
            f"- allowed values: {' | '.join(allowed)}",
        ]

    return "\n".join(lines)


def _maybe_notify_hook_result(
    *,
    session: Session,
    event_type: str,
    proc: subprocess.CompletedProcess[str],
) -> None:
    if not NOTIFY_CMD:
        append_event(
            {
                "type": "OPENCLAW_NOTIFY_SKIPPED",
                "session_id": session.session_id,
                "gateway_event_type": event_type,
                "reason": "notify command not configured",
            }
        )
        return

    reply_text = (proc.stdout or "").strip()
    if not reply_text:
        append_event(
            {
                "type": "OPENCLAW_NOTIFY_SKIPPED",
                "session_id": session.session_id,
                "gateway_event_type": event_type,
                "reason": "empty stdout",
                "source_rc": proc.returncode,
            }
        )
        return

    notify_text = f"{NOTIFY_PREFIX}{reply_text}" if NOTIFY_PREFIX else reply_text

    try:
        notify_proc = subprocess.run(
            ["bash", "-lc", NOTIFY_CMD],
            input=notify_text,
            text=True,
            capture_output=True,
            timeout=NOTIFY_TIMEOUT_SECONDS,
        )
    except Exception as e:
        append_event(
            {
                "type": "OPENCLAW_NOTIFY_RESULT",
                "ok": False,
                "session_id": session.session_id,
                "gateway_event_type": event_type,
                "notify_cmd": _truncate(NOTIFY_CMD, 240),
                "error": str(e),
            }
        )
        return

    append_event(
        {
            "type": "OPENCLAW_NOTIFY_RESULT",
            "ok": notify_proc.returncode == 0,
            "session_id": session.session_id,
            "gateway_event_type": event_type,
            "notify_cmd": _truncate(NOTIFY_CMD, 240),
            "rc": notify_proc.returncode,
            "stdout": _truncate(notify_proc.stdout),
            "stderr": _truncate(notify_proc.stderr),
        }
    )


def _emit_gateway_hook(
    *,
    session: Session,
    event_type: str,
    default_tail_text: str | None = None,
    include_default_tail: bool = False,
) -> bool:
    if not OPENCLAW_SESSION_ID:
        append_event(
            {
                "type": "OPENCLAW_AGENT_EMIT",
                "ok": False,
                "gateway_event_type": event_type,
                "session_id": session.session_id,
                "state": session.state.value,
                "error": "CODELEADER_OPENCLAW_SESSION_ID is not configured",
            }
        )
        return False

    payload = _build_gateway_hook_payload(
        session=session,
        event_type=event_type,
        default_tail_text=default_tail_text,
        include_default_tail=include_default_tail,
    )
    message_text = _format_hook_message(payload)

    try:
        proc = subprocess.run(
            [
                "openclaw",
                "agent",
                "--session-id",
                OPENCLAW_SESSION_ID,
                "--message",
                message_text,
            ],
            capture_output=True,
            text=True,
            timeout=OPENCLAW_AGENT_TIMEOUT_SECONDS,
        )
    except Exception as e:
        append_event(
            {
                "type": "OPENCLAW_AGENT_EMIT",
                "ok": False,
                "gateway_event_type": event_type,
                "session_id": session.session_id,
                "state": session.state.value,
                "control_state": session.control_state,
                "automation_blocked": session.automation_blocked,
                "reason": session.human_reason,
                "blocked_reason": session.blocked_reason,
                "include_default_tail": include_default_tail,
                "openclaw_session_id": OPENCLAW_SESSION_ID,
                "error": str(e),
            }
        )
        return False

    ok = proc.returncode == 0
    append_event(
        {
            "type": "OPENCLAW_AGENT_EMIT",
            "ok": ok,
            "gateway_event_type": event_type,
            "session_id": session.session_id,
            "state": session.state.value,
            "control_state": session.control_state,
            "automation_blocked": session.automation_blocked,
            "reason": session.human_reason,
            "blocked_reason": session.blocked_reason,
            "include_default_tail": include_default_tail,
            "openclaw_session_id": OPENCLAW_SESSION_ID,
            "rc": proc.returncode,
            "stdout": _truncate(proc.stdout),
            "stderr": _truncate(proc.stderr),
        }
    )
    _maybe_notify_hook_result(session=session, event_type=event_type, proc=proc)
    return ok



def _run_human_hook(session: Session) -> bool:
    if not HUMAN_HOOK_CMD:
        append_event(
            {
                "type": "HUMAN_HOOK_SKIPPED",
                "session_id": session.session_id,
                "state": session.state.value,
                "control_state": session.control_state,
                "reason": session.human_reason,
                "blocked_reason": session.blocked_reason,
                "detail": "hook command not configured",
            }
        )
        return False

    payload = {
        "session_id": session.session_id,
        "state": session.state.value,
        "control_state": session.control_state,
        "reason": session.human_reason,
        "blocked_reason": session.blocked_reason,
        "automation_blocked": session.automation_blocked,
    }
    env = os.environ.copy()
    env["CODELEADER_HUMAN_HOOK_PAYLOAD"] = json.dumps(payload, ensure_ascii=False)
    env["CODELEADER_SESSION_ID"] = session.session_id
    env["CODELEADER_STATE"] = session.state.value
    env["CODELEADER_CONTROL_STATE"] = session.control_state or ""
    env["CODELEADER_HUMAN_REASON"] = session.human_reason or ""
    env["CODELEADER_BLOCKED_REASON"] = session.blocked_reason or ""

    try:
        proc = subprocess.run(
            ["bash", "-lc", HUMAN_HOOK_CMD],
            env=env,
            capture_output=True,
            text=True,
            timeout=HUMAN_HOOK_TIMEOUT_SECONDS,
        )
    except Exception as e:
        append_event(
            {
                "type": "HUMAN_HOOK_ERROR",
                "session_id": session.session_id,
                "state": session.state.value,
                "control_state": session.control_state,
                "reason": session.human_reason,
                "blocked_reason": session.blocked_reason,
                "error": str(e),
            }
        )
        return False

    append_event(
        {
            "type": "HUMAN_HOOK_RESULT",
            "session_id": session.session_id,
            "state": session.state.value,
            "control_state": session.control_state,
            "reason": session.human_reason,
            "blocked_reason": session.blocked_reason,
            "rc": proc.returncode,
            "stdout": _truncate(proc.stdout),
            "stderr": _truncate(proc.stderr),
        }
    )
    return proc.returncode == 0


def _clear_human_intervention(session: Session, reason: str = "human:hook_granted") -> None:
    session.control_state = None
    session.automation_blocked = False
    if session.human_reason != "human:auto_clear_ready_for_hook":
        session.human_reason = reason
    session.human_last_input_ts = None
    session.human_idle_fired = False
    session.last_human_input_log_ts = None
    session.human_hook_pending = False
    append_event(
        {
            "type": "HUMAN_INTERVENTION_CLEARED",
            "session_id": session.session_id,
            "state": session.state.value,
            "reason": reason,
        }
    )


# Thread pool for running hooks without blocking the API.
_hook_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="hook")


def _run_hooks_in_background(session_id: str, default_tail_text: str | None) -> None:
    """Execute gateway hook + human hook in a background thread.
    Clears the human intervention lock after hooks complete."""
    try:
        s = get_session(session_id)
        _emit_gateway_hook(
            session=s,
            event_type=GATEWAY_EVENT_HUMAN_INTERVENTION_READY_FOR_HOOK,
            default_tail_text=default_tail_text,
            include_default_tail=True,
        )
        if _run_human_hook(s):
            _clear_human_intervention(s)
        else:
            _clear_human_intervention(s, reason="human:hook_failed_or_skipped")
    except Exception as e:
        # Even on error, always release the lock to prevent deadlock.
        try:
            s = get_session(session_id)
            _clear_human_intervention(s, reason=f"human:hook_error:{e}")
        except Exception:
            pass
        append_event({
            "type": "HOOK_BACKGROUND_ERROR",
            "session_id": session_id,
            "error": str(e),
        })


def _maybe_emit_human_hook_ready(session: Session) -> None:
    _sync_human_idle(session)
    if not session.automation_blocked:
        return
    if not session.human_idle_fired:
        return
    if not session.human_hook_pending:
        return
    if session.state not in {SentinelState.WAITING_FOR_PROMPT, SentinelState.BLOCKED_ON_APPROVAL}:
        return
    append_event(
        {
            "type": "HUMAN_INTERVENTION_READY_FOR_HOOK",
            "session_id": session.session_id,
            "state": session.state.value,
            "control_state": session.control_state,
            "reason": session.human_reason,
            "blocked_reason": session.blocked_reason,
        }
    )
    # Fetch context now while we still have state.
    default_tail_text = _fetch_default_tail_text()
    # Submit the heavy hook work to a background thread.
    # The lock (automation_blocked) stays active; it will be cleared
    # by the background thread after hooks finish.
    _hook_executor.submit(_run_hooks_in_background, session.session_id, default_tail_text)



def _background_tick_once() -> None:
    s = get_session("CodeLeader")
    before_idle = s.human_idle_fired
    _sync_human_idle(s)
    _flush_due_auto_hooks(s)
    if (not before_idle) and s.human_idle_fired:
        _maybe_emit_human_hook_ready(s)


def _background_tick_loop() -> None:
    while True:
        try:
            _background_tick_once()
        except Exception:
            pass
        time.sleep(1)



def _audit_signature(*, session: Session, event_type: str, reason: str | None) -> str:
    return json.dumps(
        {
            "state": public_state(session).value,
            "execution_state": session.state.value,
            "control_state": session.control_state,
            "automation_blocked": session.automation_blocked,
            "human_reason": session.human_reason,
            "blocked_reason": session.blocked_reason,
            "pending_approval_id": (session.pending_approval.approval_id if session.pending_approval else None),
            "event_type": event_type,
            "reason": reason,
        },
        ensure_ascii=False,
        sort_keys=True,
    )

def _state_response(session: Session) -> StateResponse:
    _sync_human_idle(session)
    _maybe_emit_human_hook_ready(session)
    return StateResponse(
        session_id=session.session_id,
        state=public_state(session).value,
        blocked_reason=session.blocked_reason,
        control_state=session.control_state,
        automation_blocked=session.automation_blocked,
        human_reason=session.human_reason,
    )


def _is_safe_prompt(prompt: str) -> bool:
    """Allow all inputs by default, relying on the receiving agent to interpret them safely.
    Strictly deny potentially destructive shell injections or redirection.
    """

    p = prompt.strip()
    if not p:
        return False

    # Multi-line injection remains disallowed for now.
    if "\n" in p or "\r" in p:
        return False

    # 1. 拦截危险的 Shell 操作符 (拦截组合命令、重定向、命令替换) 和 破坏性指令
    forbidden_tokens = [
        ";", "&&", "||", "|", "`", "$(", "$ (", ">", "<",
        "rm -rf", "sudo "
    ]
    if any(tok in p for tok in forbidden_tokens):
        return False

    return True


def _ssh_zellij_write(prompt: str) -> None:
    """Inject prompt + Enter into remote zellij session via ssh.

    Uses system ssh; requires key-based login (BatchMode).
    """

    # Use shlex.quote to protect the remote shell.
    quoted = shlex.quote(prompt)
    cmd = (
        f"zellij --session {shlex.quote(REMOTE_ZELLIJ_SESSION)} action write-chars {quoted} "
        f"&& zellij --session {shlex.quote(REMOTE_ZELLIJ_SESSION)} action write 13"
    )

    subprocess.run(
        ["ssh", "-o", "BatchMode=yes", REMOTE_SSH_HOST, cmd],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _approval_profile(blocked_reason: str | None) -> dict:
    reason = (blocked_reason or "").strip().lower()
    if reason in {"claude:approval_prompt_yes_always_no"}:
        return {
            "allowed": ["yes", "always", "no"],
            "mapping": {"yes": "1", "always": "2", "no": "3"},
            "mode": "yes_always_no",
        }
    if reason in {"claude:approval_prompt_generic_yes_no"}:
        return {
            "allowed": ["yes", "no"],
            "mapping": {"yes": "1", "no": "2"},
            "mode": "yes_no",
        }
    # Conservative fallback: preserve current behavior for known/legacy 3-option approvals.
    return {
        "allowed": ["yes", "always", "no"],
        "mapping": {"yes": "1", "always": "2", "no": "3"},
        "mode": "default_yes_always_no",
    }


def _ssh_zellij_approve(decision: str, blocked_reason: str | None = None) -> None:
    d = decision.strip().lower()
    profile = _approval_profile(blocked_reason)
    mapping = profile["mapping"]
    allowed = profile["allowed"]
    if d not in allowed:
        raise ValueError(f"decision must be one of: {', '.join(allowed)}")
    _ssh_zellij_write(mapping[d])


def _fetch_default_tail_text() -> str:
    return _fetch_tail_lines_text(20)


def _fetch_tail_lines_text(lines_count: int) -> str:
    shell = (
        "zellij --session '{session}' action dump-screen /tmp/cc_live_screen.txt >/dev/null 2>&1; "
        "awk 'NF {{ blank=0; lines[++n]=$0; next }} !NF {{ blank++; if (blank<=1) lines[++n]=$0 }} "
        "END {{ while (n>0 && lines[n] ~ /^$/) n--; start=(n>179?n-179:1); for (i=start; i<=n; i++) print lines[i] }}' "
        "/tmp/cc_live_screen.txt"
    ).format(session=REMOTE_ZELLIJ_SESSION)
    try:
        proc = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", REMOTE_SSH_HOST, "bash", "-lc", shell],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode != 0:
            return ""
        lines = proc.stdout.splitlines()
        if not lines:
            return ""
        return _clean_default_tail_text("\n".join(lines[-max(1, lines_count):]))
    except Exception:
        return ""


def _clean_default_tail_text(text: str) -> str:
    if not text:
        return ""

    cleaned: list[str] = []
    prev_blank = False
    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()

        is_noise = False
        if stripped in {"? for shortcuts", "esc to interrupt"}:
            is_noise = True
        elif stripped and all(ch in "─-═▔▁▕▏▎▍▌▋▊▉█▪•·⎿╭╮╰╯│ " for ch in stripped):
            is_noise = True

        if is_noise:
            continue

        if stripped == "":
            if prev_blank:
                continue
            prev_blank = True
            cleaned.append("")
            continue

        prev_blank = False
        cleaned.append(line)

    while cleaned and cleaned[0] == "":
        cleaned.pop(0)
    while cleaned and cleaned[-1] == "":
        cleaned.pop()
    return "\n".join(cleaned)


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _remote_check(remote_host: str, zellij_session: str) -> RemoteBootstrapChecks:
    """Structured prereq check for remote bootstrap (no remote writes)."""

    def _ok(cmd: str) -> bool:
        try:
            r = subprocess.run(
                ["ssh", "-o", "BatchMode=yes", remote_host, cmd],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return r.returncode == 0
        except Exception:
            return False

    python3_ok = _ok("command -v python3 >/dev/null")
    # venv probe uses /tmp but does not touch user env; OK for healthcheck.
    venv_ok = _ok("python3 -m venv /tmp/codeleader_venv_probe >/dev/null 2>&1 && rm -rf /tmp/codeleader_venv_probe")
    zellij_ok = _ok("command -v zellij >/dev/null")
    zellij_session_ok = _ok(f"zellij ls | grep -q '{zellij_session}'") if zellij_ok else None

    return RemoteBootstrapChecks(
        python3_ok=python3_ok,
        venv_ok=venv_ok,
        zellij_ok=zellij_ok,
        zellij_session_ok=zellij_session_ok,
    )


def append_event(event: dict) -> None:
    event = {"ts": _ts(), "run_id": RUN_ID or None, **event}
    with EVENTS_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def _remote_get_watcher_info(remote_host: str) -> dict:
    """Fetch watcher status from remote host via ssh.

    Returns a dict suitable for RemoteBootstrapWatcher.
    """

    # Get python version (best-effort).
    py = None
    remote_service_root = REMOTE_SERVICE_ROOT or "$HOME/.codeleader"
    try:
        r = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", remote_host, f"{remote_service_root}/venv/bin/python -V"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if r.returncode == 0:
            py = (r.stdout or r.stderr).strip()
    except Exception:
        py = None

    # Get watcher process line.
    proc = subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            remote_host,
            f"ps aux | grep -v grep | grep -F '{remote_service_root}/prompt_watcher_v2.py' || true",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    lines = (proc.stdout or "").strip().splitlines()
    cmdline = lines[0] if lines else None

    pid = None
    if cmdline:
        parts = cmdline.split()
        # ps aux format: USER PID ... CMD
        if len(parts) >= 2:
            try:
                pid = int(parts[1])
            except ValueError:
                pid = None

    # Tail err (best-effort).
    err_tail = None
    try:
        t = subprocess.run(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                remote_host,
                f"tail -n 10 {remote_service_root}/watcher_v2.err 2>/dev/null || true",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        err_tail = [ln for ln in (t.stdout or "").splitlines() if ln.strip()]
    except Exception:
        err_tail = None

    return {
        "running": bool(cmdline),
        "pid": pid,
        "cmd": cmdline,
        "python": py,
        "err_tail": err_tail,
    }


def _truncate(s: str, limit: int = 2000) -> str:
    if not s:
        return ""
    if len(s) <= limit:
        return s
    return s[:limit] + "\n...<truncated>...\n"


app = FastAPI(title="OpenClaw CodeLeader (codeleader-sentinel)", version="0.1.0")


@app.on_event("startup")
def _startup_background_tick() -> None:
    append_event(
        {
            "type": "RUN_START",
            "pid": os.getpid(),
            "session_id": SINGLE_SESSION_ID,
            "openclaw_session_id": OPENCLAW_SESSION_ID,
            "host": APP_HOST,
            "port": APP_PORT,
        }
    )
    if CURRENT_JSON.exists():
        try:
            payload = json.loads(CURRENT_JSON.read_text(encoding="utf-8"))
            payload["status"] = "running"
            payload["pid"] = os.getpid()
            payload["run_id"] = RUN_ID or payload.get("run_id")
            CURRENT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except Exception:
            pass
    t = threading.Thread(target=_background_tick_loop, daemon=True)
    t.start()

# In-memory session store (Phase-1)
_sessions: Dict[str, Session] = {}


SINGLE_SESSION_ID = "CodeLeader"


def get_session(session_id: str) -> Session:
    # v0: single-session only.
    if session_id != SINGLE_SESSION_ID:
        raise HTTPException(status_code=400, detail=f"only session_id={SINGLE_SESSION_ID!r} is supported in v0")

    s = _sessions.get(session_id)
    if s is None:
        s = Session(session_id=session_id)
        _sessions[session_id] = s
    return s


@app.get("/health")
def health() -> dict:
    return {"ok": True, "time": _ts()}


@app.get("/api/v1/session/{session_id}", response_model=StateResponse)
def get_state(session_id: str) -> StateResponse:
    s = get_session(session_id)
    return _state_response(s)


@app.post("/api/v1/session/start", response_model=StateResponse)
def start(req: StartRequest) -> StateResponse:
    # v0: single-session only. Repeated starts are denied unless the codeleader-sentinel is IDLE.
    s = get_session(req.session_id)
    if s.state != SentinelState.IDLE:
        raise HTTPException(status_code=403, detail=f"start not allowed in state={s.state.value}")

    transition_on_start(s)
    append_event({"type": "SESSION_START", "session_id": s.session_id, "state": s.state.value})
    return _state_response(s)


@app.post("/api/v1/action/send_prompt", response_model=StateResponse)
def send_prompt(session_id: str, req: SendPromptRequest) -> StateResponse:
    s = get_session(session_id)
    _sync_human_idle(s)
    if s.automation_blocked:
        raise HTTPException(
            status_code=423,
            detail="Human intervention in progress. Cannot send prompt until intervention ends.",
        )
    if not can_send_prompt(s):
        if s.pending_approval is not None:
            raise HTTPException(status_code=403, detail=f"send_prompt blocked by pending approval id={s.pending_approval.approval_id}")
        raise HTTPException(status_code=403, detail=f"send_prompt not allowed in state={public_state(s).value}")

    prompt = req.prompt

    # Phase-2 minimal: optionally execute safe prompts via ssh->zellij action.
    if ALLOW_REMOTE_EXEC:
        if not _is_safe_prompt(prompt):
            raise HTTPException(
                status_code=400,
                detail="Prompt rejected: Contains forbidden shell redirection, logic chaining operators (like &&, |, >, `) or potentially destructive commands (e.g. rm -rf, sudo). Please use natural language."
            )

    transition_on_send_prompt(s)

    if ALLOW_REMOTE_EXEC:
        try:
            _ssh_zellij_write(prompt)
        except subprocess.CalledProcessError:
            append_event(
                {
                    "type": "REMOTE_EXEC_ERROR",
                    "session_id": s.session_id,
                    "state": public_state(s).value,
                    "prompt": prompt,
                    "remote_host": REMOTE_SSH_HOST,
                    "remote_session": REMOTE_ZELLIJ_SESSION,
                }
            )
            raise HTTPException(status_code=502, detail="remote exec failed")

    append_event(
        {
            "type": "SEND_PROMPT",
            "session_id": s.session_id,
            "state": public_state(s).value,
            "prompt": prompt,
            "remote_host": REMOTE_SSH_HOST,
            "remote_session": REMOTE_ZELLIJ_SESSION,
            "executed": bool(ALLOW_REMOTE_EXEC),
        }
    )

    return _state_response(s)


@app.post("/api/v1/action/approve", response_model=StateResponse)
def approve(session_id: str, req: ApproveRequest) -> StateResponse:
    s = get_session(session_id)
    _sync_human_idle(s)
    if s.automation_blocked:
        raise HTTPException(
            status_code=423,
            detail="Human intervention in progress. Cannot approve until intervention ends.",
        )
    if not can_approve(s):
        raise HTTPException(status_code=403, detail="approve not allowed; no pending approval")

    decision = req.decision
    pending_approval_id = s.pending_approval.approval_id if s.pending_approval else None
    prior_reason = s.pending_approval.reason if s.pending_approval else s.blocked_reason
    profile = _approval_profile(prior_reason)
    allowed = profile["allowed"]

    if decision not in allowed:
        raise HTTPException(status_code=400, detail=f"decision '{decision}' not allowed for blocked_reason={prior_reason!r}; allowed={allowed}")

    if req.approval_id and pending_approval_id and req.approval_id != pending_approval_id:
        raise HTTPException(status_code=409, detail=f"stale approval_id: got={req.approval_id}, current={pending_approval_id}")

    transition_on_approve(s)

    if ALLOW_REMOTE_EXEC:
        try:
            _ssh_zellij_approve(decision, prior_reason)
        except (ValueError, subprocess.CalledProcessError):
            append_event(
                {
                    "type": "REMOTE_APPROVE_ERROR",
                    "session_id": s.session_id,
                    "state": public_state(s).value,
                    "decision": decision,
                    "approval_id": pending_approval_id,
                    "reason": prior_reason,
                    "remote_host": REMOTE_SSH_HOST,
                    "remote_session": REMOTE_ZELLIJ_SESSION,
                }
            )
            raise HTTPException(status_code=502, detail="remote approve failed")

    append_event(
        {
            "type": "APPROVE",
            "session_id": s.session_id,
            "state": public_state(s).value,
            "decision": decision,
            "approval_id": pending_approval_id,
            "reason": prior_reason,
            "remote_host": REMOTE_SSH_HOST,
            "remote_session": REMOTE_ZELLIJ_SESSION,
            "executed": bool(ALLOW_REMOTE_EXEC),
        }
    )

    return _state_response(s)


@app.post("/api/v1/remote/bootstrap", response_model=RemoteBootstrapResponse)
def remote_bootstrap(req: RemoteBootstrapRequest) -> RemoteBootstrapResponse:
    action = req.action

    # Resolve overrides (default to env-derived globals).
    remote_host = (req.remote_host or REMOTE_SSH_HOST).strip()
    zellij_session = (req.zellij_session or REMOTE_ZELLIJ_SESSION).strip()
    webhook_url = (
        req.webhook_url
        or os.environ.get("CODELEADER_REMOTE_WEBHOOK_URL", "http://127.0.0.1:18787/webhook/zellij/state_change")
    ).strip()

    # Enforce gates: read-only actions always allowed; write/start/stop require explicit opt-in.
    if action in {"apply", "start", "stop"} and not ALLOW_REMOTE_BOOTSTRAP:
        raise HTTPException(status_code=403, detail="remote bootstrap disabled (set CODELEADER_ALLOW_REMOTE_BOOTSTRAP=1)")

    script = str((ROOT / "scripts" / "bootstrap_remote.sh").resolve())
    if not Path(script).exists():
        raise HTTPException(status_code=500, detail="bootstrap script missing")

    arg = f"--{action}"

    env = os.environ.copy()
    env["CODELEADER_REMOTE_SSH_HOST"] = remote_host
    env["CODELEADER_REMOTE_ZELLIJ_SESSION"] = zellij_session
    env["CODELEADER_REMOTE_WEBHOOK_URL"] = webhook_url

    # Run script and capture output (truncate in response + logs).
    p = subprocess.run(
        ["bash", script, arg],
        env=env,
        capture_output=True,
        text=True,
    )

    stdout = _truncate(p.stdout)
    stderr = _truncate(p.stderr)

    # Structured checks for remote prerequisites.
    checks = None
    if action == "check":
        checks = _remote_check(remote_host, zellij_session)

    # Structured watcher info (so callers don't need to parse stdout).
    watcher = None
    if action in {"status", "start"}:
        watcher = RemoteBootstrapWatcher(**_remote_get_watcher_info(remote_host))
    elif action == "stop":
        watcher = RemoteBootstrapWatcher(running=False)

    append_event(
        {
            "type": "REMOTE_BOOTSTRAP",
            "action": action,
            "rc": p.returncode,
            "ok": (p.returncode == 0),
            "remote_host": remote_host,
            "remote_session": zellij_session,
            "webhook_url": webhook_url,
            "stdout": stdout,
            "stderr": stderr,
            "watcher": watcher.model_dump() if watcher else None,
            "checks": checks.model_dump() if checks else None,
        }
    )

    return RemoteBootstrapResponse(
        ok=(p.returncode == 0),
        action=action,
        rc=p.returncode,
        stdout=stdout,
        stderr=stderr,
        remote_host=remote_host,
        zellij_session=zellij_session,
        webhook_url=webhook_url,
        running=(watcher.running if watcher else None),
        pid=(watcher.pid if watcher else None),
        watcher=watcher,
        checks=checks,
    )


@app.post("/webhook/zellij/state_change", response_model=StateResponse)
def webhook_state_change(payload: WebhookStateChange) -> StateResponse:
    s = get_session(payload.session_id)
    _sync_human_idle(s)
    prev_state = s.state.value
    prev_public_state = public_state(s).value
    prev_control = s.control_state
    et = (payload.event_type or "").upper()
    if et == "HUMAN_INPUT":
        # Suppress HUMAN_INPUT during automation cooldown period.
        # When send_prompt/approve types text into the terminal, the screen changes
        # and the plugin falsely reports it as human input.
        now = time.time()
        if s.last_automation_action_ts and (now - s.last_automation_action_ts) < AUTOMATION_COOLDOWN_SECONDS:
            append_event({
                "type": "HUMAN_INPUT_SUPPRESSED_COOLDOWN",
                "session_id": s.session_id,
                "cooldown_remaining": round(AUTOMATION_COOLDOWN_SECONDS - (now - s.last_automation_action_ts), 1),
            })
            return _state_response(s)

        if not s.automation_blocked:
            _clear_all_pending_auto_hooks(s, "human_intervention_started")
            transition_on_human_input(s, time.time())
            _emit_gateway_hook(
                session=s,
                event_type=GATEWAY_EVENT_HUMAN_INTERVENTION_STARTED,
                include_default_tail=False,
            )
            append_event({
                "type": "HUMAN_INTERVENTION_STARTED",
                "session_id": s.session_id,
            })
        else:
            s.human_last_input_ts = time.time()
            s.human_idle_fired = False
        return _state_response(s)

    obs = normalize_observation(
        payload.event_type,
        payload.reason,
        payload.raw_context,
        payload.fingerprint,
    )
    apply_observation(s, obs)
    bootstrap_active = _bootstrap_active(s)
    _maybe_emit_human_hook_ready(s)

    entered_blocked = prev_public_state != SentinelState.BLOCKED_ON_APPROVAL.value and s.pending_approval is not None
    entered_waiting = prev_public_state != SentinelState.WAITING_FOR_PROMPT.value and public_state(s) == SentinelState.WAITING_FOR_PROMPT

    if bootstrap_active and (not s.automation_blocked) and entered_blocked:
        default_tail_text = _fetch_default_tail_text()
        _enqueue_auto_hook(s, GATEWAY_EVENT_AUTO_FLOW_BLOCKED_ON_APPROVAL, default_tail_text)
    elif bootstrap_active and (not s.automation_blocked) and entered_waiting and s.pending_approval is None:
        default_tail_text = _fetch_default_tail_text()
        if not s.baseline_ready_seen:
            s.baseline_ready_seen = True
            append_event(
                {
                    "type": "AUTO_HOOK_SUPPRESSED",
                    "session_id": s.session_id,
                    "reason": "baseline_ready_transition",
                    "event_type": GATEWAY_EVENT_AUTO_FLOW_COMPLETED,
                }
            )
        elif not _tail_looks_like_welcome_idle(default_tail_text):
            _enqueue_auto_hook(s, GATEWAY_EVENT_AUTO_FLOW_COMPLETED, default_tail_text)
        else:
            append_event(
                {
                    "type": "AUTO_HOOK_DROPPED",
                    "session_id": s.session_id,
                    "original_event_type": GATEWAY_EVENT_AUTO_FLOW_COMPLETED,
                    "reason": "welcome_idle_prompt_ready_ignored",
                }
            )
    elif not bootstrap_active:
        append_event(
            {
                "type": "AUTO_HOOK_SUPPRESSED",
                "session_id": s.session_id,
                "reason": "bootstrap_phase",
                "event_type": payload.event_type,
            }
        )

    changed = (public_state(s).value != prev_public_state) or (s.state.value != prev_state)
    should_log = changed or et != "PROMPT_READY" or LOG_PROMPT_READY_HEARTBEAT
    if s.control_state == "HUMAN_INTERVENING" and et in {"PROMPT_READY", "UNKNOWN"}:
        should_log = False
    if should_log:
        signature = _audit_signature(session=s, event_type=payload.event_type, reason=payload.reason)
        if signature != s.last_audit_signature:
            append_event(
                {
                    "type": "WEBHOOK",
                    "session_id": s.session_id,
                    "prev_state": prev_state,
                    "prev_public_state": prev_public_state,
                    "state": s.state.value,
                    "public_state": public_state(s).value,
                    "event_type": payload.event_type,
                    "reason": payload.reason,
                    "control_state": s.control_state,
                    "automation_blocked": s.automation_blocked,
                    "human_reason": s.human_reason,
                    "prev_control_state": prev_control,
                    "pending_approval_id": (s.pending_approval.approval_id if s.pending_approval else None),
                    "logged_by": (
                        "changed"
                        if changed
                        else ("prompt_ready_heartbeat" if et == "PROMPT_READY" else "event")
                    ),
                }
            )
            s.last_audit_signature = signature

    return _state_response(s)


@app.post("/api/v1/context/read_tail_lines")
def read_tail_lines(req: TailLinesRequest) -> dict:
    s = get_session(req.session_id)
    tail_text = _fetch_tail_lines_text(req.lines)
    return {
        "session_id": s.session_id,
        "semantic_state": public_state(s).value,
        "control_state": s.control_state,
        "automation_blocked": s.automation_blocked,
        "lines": req.lines,
        "tail_text": tail_text,
    }


@app.post("/api/v1/session/destroy", response_model=StateResponse)
def destroy(req: StartRequest) -> StateResponse:
    s = get_session(req.session_id)
    transition_on_destroy(s)
    append_event({"type": "SESSION_DESTROY", "session_id": s.session_id, "state": s.state.value})
    return _state_response(s)


if __name__ == "__main__":
    import uvicorn

    # When running as a script, pass the app object directly.
    uvicorn.run(app, host=APP_HOST, port=APP_PORT, reload=False)
