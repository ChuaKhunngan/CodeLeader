#!/usr/bin/env bash
set -euo pipefail

# Stop Local codeleader-sentinel (Phase-1) gracefully.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="$ROOT_DIR/runtime"
PID_FILE="$RUNTIME_DIR/codeleader-sentinel.pid"
CURRENT_JSON="$RUNTIME_DIR/current.json"

HOST="${CODELEADER_SENTINEL_HOST:-${SENTINEL_HOST:-127.0.0.1}}"
PORT="${CODELEADER_SENTINEL_PORT:-${SENTINEL_PORT:-8787}}"

# Optional: stop ssh tunnel if it was started alongside sentinel.
TUNNEL_PID_FILE="$RUNTIME_DIR/codeleader-tunnel.pid"

if [[ ! -f "$PID_FILE" ]]; then
  echo "Sentinel not running (no pid file)."
else
  pid="$(cat "$PID_FILE" || true)"
  if [[ -z "$pid" ]]; then
    rm -f "$PID_FILE"
    echo "Sentinel not running (empty pid)."
  elif ! kill -0 "$pid" 2>/dev/null; then
    rm -f "$PID_FILE"
    echo "Sentinel not running (stale pid=$pid)."
  else
    # Best-effort: destroy single session state before shutdown.
    curl -s -X POST "http://$HOST:$PORT/api/v1/session/destroy" \
      -H 'content-type: application/json' \
      -d '{"session_id":"CodeLeader"}' >/dev/null 2>&1 || true

    kill -TERM "$pid" 2>/dev/null || true

    # Wait for exit.
    for i in {1..30}; do
      if ! kill -0 "$pid" 2>/dev/null; then
        rm -f "$PID_FILE"
        echo "Sentinel stopped."
        break
      fi
      sleep 0.2
    done

    if [[ -f "$PID_FILE" ]]; then
      echo "Sentinel did not stop in time; sending SIGKILL." >&2
      kill -KILL "$pid" 2>/dev/null || true
      rm -f "$PID_FILE"
    fi
  fi
fi

# Stop tunnel last.
if [[ -f "$TUNNEL_PID_FILE" ]]; then
  tpid="$(cat "$TUNNEL_PID_FILE" || true)"
  if [[ -n "$tpid" ]] && kill -0 "$tpid" 2>/dev/null; then
    kill -TERM "$tpid" 2>/dev/null || true
    # Give it a moment.
    sleep 0.2
    if kill -0 "$tpid" 2>/dev/null; then
      kill -KILL "$tpid" 2>/dev/null || true
    fi
    echo "Tunnel stopped."
  fi
  rm -f "$TUNNEL_PID_FILE" || true
fi

if [[ -f "$CURRENT_JSON" ]]; then
  python3 - <<PY
import json
from pathlib import Path
path = Path("""$CURRENT_JSON""")
payload = json.loads(path.read_text(encoding='utf-8'))
payload['status'] = 'stopped'
path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding='utf-8')
PY
fi
