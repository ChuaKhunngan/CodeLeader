from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import time

HUMAN_IDLE_TIMEOUT_SECONDS = 30
AUTO_HOOK_DELAY_SECONDS = 5
BOOTSTRAP_GRACE_SECONDS = 8
AUTOMATION_COOLDOWN_SECONDS = 10


class SentinelState(str, Enum):
    IDLE = "IDLE"
    WORKING = "WORKING"
    WAITING_FOR_PROMPT = "WAITING_FOR_PROMPT"
    BLOCKED_ON_APPROVAL = "BLOCKED_ON_APPROVAL"


@dataclass
class PendingApproval:
    approval_id: str
    reason: Optional[str] = None
    raw_context: Optional[str] = None
    fingerprint: Optional[str] = None
    created_ts: float = field(default_factory=time.time)
    source_event_type: str = "BLOCKED_ON_APPROVAL"


@dataclass
class PendingAutoHook:
    hook_id: str
    event_type: str
    default_tail_text: str
    due_ts: float
    created_ts: float = field(default_factory=time.time)


@dataclass
class Session:
    # Single-session v0: a stable id owned by the Sentinel process.
    session_id: str
    state: SentinelState = SentinelState.IDLE
    blocked_reason: Optional[str] = None
    control_state: Optional[str] = None
    automation_blocked: bool = False
    human_reason: Optional[str] = None
    human_last_input_ts: Optional[float] = None
    human_idle_fired: bool = False
    last_human_input_log_ts: Optional[float] = None
    human_hook_pending: bool = False
    last_audit_signature: Optional[str] = None
    approval_seq: int = 0
    pending_approval: Optional[PendingApproval] = None
    auto_hook_seq: int = 0
    pending_auto_hooks: list[PendingAutoHook] = field(default_factory=list)
    last_working_observed_ts: Optional[float] = None
    last_ready_observed_ts: Optional[float] = None
    bootstrap_phase: bool = True
    bootstrap_started_ts: float = field(default_factory=time.time)
    baseline_ready_seen: bool = False
    last_automation_action_ts: Optional[float] = None


@dataclass
class Observation:
    semantic_state: str
    reason: Optional[str] = None
    raw_context: Optional[str] = None
    fingerprint: Optional[str] = None
    observed_at: float = field(default_factory=time.time)


def public_state(session: Session) -> SentinelState:
    if session.pending_approval is not None:
        return SentinelState.BLOCKED_ON_APPROVAL
    return session.state


def can_send_prompt(session: Session) -> bool:
    return public_state(session) == SentinelState.WAITING_FOR_PROMPT


def can_approve(session: Session) -> bool:
    return session.pending_approval is not None


def transition_on_start(session: Session) -> Session:
    # v0: START must not assume the remote is ready.
    session.state = SentinelState.IDLE
    session.blocked_reason = None
    session.control_state = None
    session.automation_blocked = False
    session.human_reason = None
    session.human_last_input_ts = None
    session.human_idle_fired = False
    session.last_human_input_log_ts = None
    session.human_hook_pending = False
    session.last_audit_signature = None
    session.approval_seq = 0
    session.pending_approval = None
    session.auto_hook_seq = 0
    session.pending_auto_hooks = []
    session.last_working_observed_ts = None
    session.last_ready_observed_ts = None
    session.bootstrap_phase = True
    session.bootstrap_started_ts = time.time()
    session.baseline_ready_seen = False
    return session


def transition_on_destroy(session: Session) -> Session:
    session.state = SentinelState.IDLE
    session.blocked_reason = None
    session.control_state = None
    session.automation_blocked = False
    session.human_reason = None
    session.human_last_input_ts = None
    session.human_idle_fired = False
    session.last_human_input_log_ts = None
    session.human_hook_pending = False
    session.last_audit_signature = None
    session.approval_seq = 0
    session.pending_approval = None
    session.auto_hook_seq = 0
    session.pending_auto_hooks = []
    session.last_working_observed_ts = None
    session.last_ready_observed_ts = None
    session.bootstrap_phase = True
    session.bootstrap_started_ts = time.time()
    session.baseline_ready_seen = False
    return session


def transition_on_send_prompt(session: Session) -> Session:
    session.state = SentinelState.WORKING
    session.blocked_reason = None
    session.control_state = None
    session.automation_blocked = False
    session.last_automation_action_ts = time.time()
    return session


def transition_on_approve(session: Session) -> Session:
    session.state = SentinelState.WORKING
    session.blocked_reason = None
    session.pending_approval = None
    session.control_state = None
    session.automation_blocked = False
    session.last_automation_action_ts = time.time()
    return session


def normalize_observation(event_type: str, reason: Optional[str], raw_context: Optional[str], fingerprint: Optional[str] = None) -> Observation:
    et = (event_type or "").upper()
    if et in {"WAITING_FOR_PROMPT"}:
        et = "PROMPT_READY"
    elif et in {"BLOCKED_ON_APPROVAL"}:
        et = "BLOCKED"
    return Observation(
        semantic_state=et,
        reason=reason,
        raw_context=raw_context,
        fingerprint=fingerprint,
    )


def apply_observation(session: Session, obs: Observation) -> Session:
    et = obs.semantic_state

    if et == "PROMPT_READY":
        if session.state != SentinelState.WAITING_FOR_PROMPT:
            session.state = SentinelState.WAITING_FOR_PROMPT
        session.blocked_reason = None
        session.pending_approval = None
        session.last_ready_observed_ts = obs.observed_at
    elif et == "WORKING":
        session.state = SentinelState.WORKING
        session.blocked_reason = None
        session.last_working_observed_ts = obs.observed_at
    elif et == "BLOCKED":
        session.state = SentinelState.BLOCKED_ON_APPROVAL
        session.blocked_reason = obs.reason
        session.last_ready_observed_ts = None
        same_block = (
            session.pending_approval is not None
            and session.pending_approval.fingerprint is not None
            and obs.fingerprint is not None
            and session.pending_approval.fingerprint == obs.fingerprint
        )
        if not same_block:
            session.approval_seq += 1
            session.pending_approval = PendingApproval(
                approval_id=f"{session.session_id}:approval:{session.approval_seq}",
                reason=obs.reason,
                raw_context=obs.raw_context,
                fingerprint=obs.fingerprint,
                source_event_type=et,
            )
    elif et == "FINISHED":
        session.state = SentinelState.WAITING_FOR_PROMPT
        session.blocked_reason = None
        session.pending_approval = None
    elif et == "RESUMED_BY_HUMAN":
        session.state = SentinelState.WORKING
        session.blocked_reason = None
        session.pending_approval = None
    elif et == "CODEAI EXITED":
        session.state = SentinelState.IDLE
        session.blocked_reason = obs.reason
        session.pending_approval = None
    else:
        pass
    return session


def transition_on_human_input(session: Session, now_ts: float) -> Session:
    if not session.automation_blocked:
        session.control_state = "HUMAN_INTERVENING"
        session.automation_blocked = True
        session.human_reason = "human:input_active"
        session.human_idle_fired = False
        session.human_hook_pending = True
    session.human_last_input_ts = now_ts
    return session


def maybe_mark_human_idle(session: Session, now_ts: float) -> bool:
    if not session.automation_blocked or session.human_last_input_ts is None or session.human_idle_fired:
        return False
    if (now_ts - session.human_last_input_ts) < HUMAN_IDLE_TIMEOUT_SECONDS:
        return False
    session.human_reason = "human:input_idle_timeout"
    session.human_idle_fired = True
    return True
