#!/usr/bin/env python3
"""Minimal CodeLeader remote watcher v2.

v1 tried to read stdin, but that doesn't observe a running interactive shell in zellij.
This v2 version polls the focused pane output via:
  zellij --session <session> action dump-screen <file>

Then scans dumped text for prompt/block patterns and POSTs webhooks back to local sentinel.

Safety:
- Observes only (no command execution besides zellij dump-screen)
- Rate-limited posts
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path


def post_json(url: str, payload: dict, timeout_s: float) -> None:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        resp.read()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--session", default=os.environ.get("CODELEADER_REMOTE_ZELLIJ_SESSION", "CodeLeader"))
    ap.add_argument("--session-id", default=os.environ.get("CODELEADER_SESSION_ID", "CodeLeader"))
    ap.add_argument("--interval", type=float, default=0.8)
    ap.add_argument("--timeout", type=float, default=2.0)
    ap.add_argument(
        "--prompt-regex",
        # v2 default: match ANY shell-prompt marker in the dumped screen (zellij dump-screen)
        # e.g., "user@host:~$ " or "root@host:# "
        default=os.environ.get("CODELEADER_PROMPT_REGEX", r"[#$] "),
    )
    ap.add_argument(
        "--blocked-regex",
        default=os.environ.get("CODELEADER_BLOCKED_REGEX", r"Proceed\? \(Y/n\)"),
    )
    ap.add_argument("--dump-path", default=os.environ.get("CODELEADER_DUMP_PATH", "/tmp/codeleader_screen.txt"))

    args = ap.parse_args()

    prompt_re = re.compile(args.prompt_regex)
    blocked_re = re.compile(args.blocked_regex)
    dump_path = Path(args.dump_path)

    last_sent: dict[str, float] = {}

    def maybe_send(event_type: str, reason: str | None = None) -> None:
        now = time.time()
        # Rate-limit per event type.
        if now - last_sent.get(event_type, 0.0) < args.interval:
            return
        payload = {"session_id": args.session_id, "event_type": event_type}
        if reason:
            payload["reason"] = reason
        try:
            post_json(args.url, payload, timeout_s=args.timeout)
            last_sent[event_type] = now
            print(f"[watcher] sent {event_type}", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"[watcher] post failed: {e}", file=sys.stderr, flush=True)

    last_prompt_ready = False

    while True:
        # Dump focused pane screen to a file.
        rc = os.system(f"zellij --session {args.session} action dump-screen {dump_path} >/dev/null 2>&1")
        if rc != 0:
            time.sleep(args.interval)
            continue
        try:
            text = dump_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            time.sleep(args.interval)
            continue

        if blocked_re.search(text):
            last_prompt_ready = False
            maybe_send("BLOCKED", reason="Proceed? (Y/n)")
        else:
            pr = bool(prompt_re.search(text))
            # Only emit PROMPT_READY on the rising edge to avoid spam.
            if pr and not last_prompt_ready:
                maybe_send("PROMPT_READY")
            last_prompt_ready = pr

        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
