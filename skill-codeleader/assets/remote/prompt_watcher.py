#!/usr/bin/env python3
"""CodeLeader remote prompt watcher (minimal)

Goal:
- Run on the remote host inside the CodeLeader zellij pane.
- Detect a minimal set of events from the terminal output stream:
  - PROMPT_READY (shell prompt seen)
  - BLOCKED (common confirmation prompt like "Proceed? (Y/n)")
- POST events back to local codeleader-sentinel webhook:
    POST {SENTINEL_WEBHOOK_URL}
      {"session_id":"CodeLeader","event_type":"PROMPT_READY"}

Notes / safety:
- This is intentionally minimal and heuristic-based.
- It does not execute commands; it only observes stdout/stderr of the shell.
- If no prompt pattern is provided, it defaults to a conservative regex that matches
  typical prompts like "$ " or "# ".

Usage (remote):
  python3 remote/prompt_watcher.py --url http://<local-ip>:8787/webhook/zellij/state_change

Recommended: run inside zellij pane to observe the interactive shell output.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from typing import Optional

import urllib.request


@dataclass
class Config:
    url: str
    session_id: str
    prompt_re: re.Pattern
    blocked_re: re.Pattern
    min_interval_s: float
    timeout_s: float


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
    ap.add_argument("--url", required=True, help="Local sentinel webhook URL")
    ap.add_argument("--session-id", default=os.environ.get("CODELEADER_SESSION_ID", "CodeLeader"))
    ap.add_argument(
        "--prompt-regex",
        default=os.environ.get("CODELEADER_PROMPT_REGEX", r"(^|\n).*([#$] )$"),
        help="Regex to detect prompt-ready lines",
    )
    ap.add_argument(
        "--blocked-regex",
        default=os.environ.get("CODELEADER_BLOCKED_REGEX", r"Proceed\? \(Y/n\)"),
        help="Regex to detect blocked confirmation prompts",
    )
    ap.add_argument("--min-interval", type=float, default=0.8, help="Minimum seconds between posts")
    ap.add_argument("--timeout", type=float, default=2.0, help="HTTP timeout seconds")

    args = ap.parse_args()

    cfg = Config(
        url=args.url,
        session_id=args.session_id,
        prompt_re=re.compile(args.prompt_regex),
        blocked_re=re.compile(args.blocked_regex),
        min_interval_s=args.min_interval,
        timeout_s=args.timeout,
    )

    last_sent: dict[str, float] = {}

    def maybe_send(event_type: str, reason: Optional[str] = None) -> None:
        now = time.time()
        t = last_sent.get(event_type, 0.0)
        if now - t < cfg.min_interval_s:
            return
        payload = {"session_id": cfg.session_id, "event_type": event_type}
        if reason:
            payload["reason"] = reason
        try:
            post_json(cfg.url, payload, timeout_s=cfg.timeout_s)
            last_sent[event_type] = now
            print(f"[watcher] sent {event_type}", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"[watcher] post failed: {e}", file=sys.stderr, flush=True)

    buf = ""
    while True:
        ch = sys.stdin.read(1)
        if ch == "":
            time.sleep(0.1)
            continue
        buf += ch
        if len(buf) > 4096:
            buf = buf[-2048:]

        if cfg.blocked_re.search(buf):
            maybe_send("BLOCKED", reason="Proceed? (Y/n)")
            buf = buf[-512:]
            continue

        if cfg.prompt_re.search(buf):
            maybe_send("PROMPT_READY")
            buf = buf[-512:]


if __name__ == "__main__":
    raise SystemExit(main())
