#!/usr/bin/env bash
set -euo pipefail

# Start Local codeleader-sentinel (Phase-1) in background and record PID.
# All runtime artifacts stay inside this skill bundle.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="$ROOT_DIR/runtime"
RUNS_DIR="$RUNTIME_DIR/runs"
RUN_ID="${CODELEADER_RUN_ID:-$(date +%Y%m%d-%H%M%S)}"
RUN_DIR="$RUNS_DIR/$RUN_ID"
LATEST_LINK="$RUNTIME_DIR/latest"
CURRENT_JSON="$RUNTIME_DIR/current.json"
PID_FILE="$RUNTIME_DIR/codeleader-sentinel.pid"
TUNNEL_PID_FILE="$RUNTIME_DIR/codeleader-tunnel.pid"
LOG_FILE="$RUN_DIR/uvicorn.log"
TUNNEL_LOG_FILE="$RUN_DIR/tunnel.log"
META_FILE="$RUN_DIR/meta.json"

HOST="${CODELEADER_SENTINEL_HOST:-${SENTINEL_HOST:-127.0.0.1}}"
PORT="${CODELEADER_SENTINEL_PORT:-${SENTINEL_PORT:-8787}}"
OPENCLAW_SESSION_ID="${CODELEADER_OPENCLAW_SESSION_ID:-}"

if [[ -z "$OPENCLAW_SESSION_ID" ]]; then
  echo "ERROR: CODELEADER_OPENCLAW_SESSION_ID is required."
  exit 2
fi
OPENCLAW_SESSION_ID="${CODELEADER_OPENCLAW_SESSION_ID:-}"

# Optional: start an SSH reverse tunnel for remote->local webhook callbacks.
# This keeps the sentinel loopback-only while allowing remote components to POST to 127.0.0.1:<REMOTE_TUNNEL_PORT>.
ENABLE_TUNNEL="${CODELEADER_ENABLE_TUNNEL:-0}"
TUNNEL_REMOTE_HOST="${CODELEADER_TUNNEL_REMOTE_HOST:-${CODELEADER_REMOTE_SSH_HOST:-}}"
if [[ "$ENABLE_TUNNEL" == "1" || "$ENABLE_TUNNEL" == "true" || "$ENABLE_TUNNEL" == "TRUE" || "$ENABLE_TUNNEL" == "yes" || "$ENABLE_TUNNEL" == "YES" ]]; then
  if [[ -z "$TUNNEL_REMOTE_HOST" ]]; then
    echo "ERROR: CODELEADER_TUNNEL_REMOTE_HOST or CODELEADER_REMOTE_SSH_HOST is required when tunnel is enabled." >&2
    exit 2
  fi
fi
# Remote port (on remote loopback) that forwards back to local sentinel PORT.
TUNNEL_REMOTE_PORT="${CODELEADER_TUNNEL_REMOTE_PORT:-18787}"
REMOTE_REPO_DIR="${CODELEADER_REMOTE_REPO_DIR:-}"
REMOTE_SESSION="${CODELEADER_REMOTE_ZELLIJ_SESSION:-CodeLeader}"

cd "$ROOT_DIR"  # skill bundle root

if [[ -f "$PID_FILE" ]]; then
  old_pid="$(cat "$PID_FILE" || true)"
  if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null; then
    echo "Sentinel already running (pid=$old_pid)."
    exit 0
  fi
fi

if [[ -z "$OPENCLAW_SESSION_ID" ]]; then
  echo "ERROR: CODELEADER_OPENCLAW_SESSION_ID is required." >&2
  exit 2
fi

mkdir -p "$RUN_DIR"
ln -sfn "$RUN_DIR" "$LATEST_LINK"

cat >"$META_FILE" <<EOF
{
  "run_id": "$RUN_ID",
  "started_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "host": "$HOST",
  "port": $PORT,
  "session_id": "$REMOTE_SESSION",
  "openclaw_session_id": "$OPENCLAW_SESSION_ID",
  "remote_host": "$TUNNEL_REMOTE_HOST",
  "remote_repo_dir": "$REMOTE_REPO_DIR"
}
EOF

# Start in background, capture PID.
# Note: uv creates/uses its own venv cache; no artifacts are written outside this project except uv cache.
nohup env \
  CODELEADER_RUN_ID="$RUN_ID" \
  CODELEADER_RUN_DIR="$RUN_DIR" \
  uv run --with fastapi --with uvicorn --with pydantic \
  "$ROOT_DIR/sentinel/app.py" \
  >"$LOG_FILE" 2>&1 &

echo $! >"$PID_FILE"
PID="$(cat "$PID_FILE")"

python3 - <<PY
import json
from pathlib import Path
path = Path("""$CURRENT_JSON""")
payload = {
  "run_id": """$RUN_ID""",
  "status": "starting",
  "pid": int("""$PID"""),
  "started_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "openclaw_session_id": """$OPENCLAW_SESSION_ID""",
  "remote_host": """$TUNNEL_REMOTE_HOST""",
  "remote_repo_dir": """$REMOTE_REPO_DIR""",
  "run_dir": """$RUN_DIR""",
}
path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

# Wait briefly for health.
for i in {1..20}; do
  if curl -s "http://$HOST:$PORT/health" >/dev/null 2>&1; then
    echo "Sentinel started: http://$HOST:$PORT (pid=$(cat "$PID_FILE"), run_id=$RUN_ID)"
    python3 - <<PY
import json
from pathlib import Path
path = Path("""$CURRENT_JSON""")
payload = json.loads(path.read_text(encoding='utf-8'))
payload['status'] = 'running'
path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding='utf-8')
PY
    break
  fi
  sleep 0.2
done

if ! kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "Sentinel did not become healthy in time. Check: $LOG_FILE" >&2
  python3 - <<PY
import json
from pathlib import Path
path = Path("""$CURRENT_JSON""")
payload = json.loads(path.read_text(encoding='utf-8'))
payload['status'] = 'failed'
path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding='utf-8')
PY
  exit 1
fi

# Start tunnel after sentinel is up.
if [[ "$ENABLE_TUNNEL" == "1" || "$ENABLE_TUNNEL" == "true" || "$ENABLE_TUNNEL" == "TRUE" || "$ENABLE_TUNNEL" == "yes" || "$ENABLE_TUNNEL" == "YES" ]]; then
  # If an old tunnel is running, keep it.
  if [[ -f "$TUNNEL_PID_FILE" ]]; then
    tpid="$(cat "$TUNNEL_PID_FILE" || true)"
    if [[ -n "$tpid" ]] && kill -0 "$tpid" 2>/dev/null; then
      echo "Tunnel already running (pid=$tpid)."
      exit 0
    fi
  fi

  # -R <remote_port>:127.0.0.1:<local_port>
  # -N: no remote command; -T: no TTY; ExitOnForwardFailure: fail fast.
  nohup ssh -N -T \
    -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=3 \
    -R "${TUNNEL_REMOTE_PORT}:127.0.0.1:${PORT}" \
    "$TUNNEL_REMOTE_HOST" \
    >"$TUNNEL_LOG_FILE" 2>&1 &

  echo $! >"$TUNNEL_PID_FILE"
  echo "Tunnel started: remote 127.0.0.1:${TUNNEL_REMOTE_PORT} -> local 127.0.0.1:${PORT} (pid=$(cat "$TUNNEL_PID_FILE"), run_id=$RUN_ID)"
fi

exit 0
