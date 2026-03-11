#!/usr/bin/env bash
set -euo pipefail

# CodeLeader remote bootstrap (MVP)
# Hard constraints:
# - Only writes under <remote-home>/.codeleader/
# - Strongly prefers isolated venv under .codeleader/venv
# - Does NOT run pip / conda / modify shell rc files

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE_HOST="${CODELEADER_REMOTE_SSH_HOST:-}"
if [[ -z "$REMOTE_HOST" ]]; then
  echo "ERROR: CODELEADER_REMOTE_SSH_HOST is required." >&2
  exit 2
fi
REMOTE_USER_HOME="${CODELEADER_REMOTE_HOME:-}"
if [[ -z "$REMOTE_USER_HOME" ]]; then
  REMOTE_USER_HOME="$(ssh -o BatchMode=yes "$REMOTE_HOST" 'printf %s "$HOME"')"
fi
REMOTE_SERVICE_ROOT="${CODELEADER_REMOTE_SERVICE_ROOT:-$REMOTE_USER_HOME/.codeleader}"
REMOTE_HOME_DIR="$REMOTE_SERVICE_ROOT"
REMOTE_VENV_DIR="$REMOTE_HOME_DIR/venv"
REMOTE_WATCHER="$REMOTE_HOME_DIR/prompt_watcher_v2.py"
REMOTE_ERR="$REMOTE_HOME_DIR/watcher_v2.err"
REMOTE_SESSION="${CODELEADER_REMOTE_ZELLIJ_SESSION:-CodeLeader}"
# Remote->local reverse tunnel URL (remote loopback).
WEBHOOK_URL="${CODELEADER_REMOTE_WEBHOOK_URL:-http://127.0.0.1:18787/webhook/zellij/state_change}"

SSH=(ssh -o BatchMode=yes)

usage() {
  cat <<EOF
Usage: $0 [--check|--apply|--start|--stop|--status]

Env:
  CODELEADER_REMOTE_SSH_HOST        (required)
  CODELEADER_REMOTE_HOME            (default: remote \$HOME)
  CODELEADER_REMOTE_SERVICE_ROOT    (default: <REMOTE_HOME>/.codeleader)
  CODELEADER_REMOTE_ZELLIJ_SESSION  (default: CodeLeader)
  CODELEADER_REMOTE_WEBHOOK_URL     (default: http://127.0.0.1:18787/webhook/zellij/state_change)

Notes:
  - Creates venv at:   $REMOTE_VENV_DIR
  - Deploys watcher:   $REMOTE_WATCHER
  - Logs to:           $REMOTE_ERR
EOF
}

remote() {
  "${SSH[@]}" "$REMOTE_HOST" "$@"
}

check_prereqs() {
  remote "set -e; command -v python3 >/dev/null; python3 -m venv /tmp/codeleader_venv_probe >/dev/null 2>&1; rm -rf /tmp/codeleader_venv_probe; command -v zellij >/dev/null"
}

ensure_dirs() {
  remote "set -e; mkdir -p '$REMOTE_HOME_DIR' '$REMOTE_HOME_DIR/bin'"
}

ensure_venv() {
  # Create venv if missing; fail if venv cannot be created.
  remote "set -e; if [ ! -x '$REMOTE_VENV_DIR/bin/python' ]; then python3 -m venv '$REMOTE_VENV_DIR'; fi; '$REMOTE_VENV_DIR/bin/python' -V >/dev/null"
}

deploy_watcher() {
  # Upload watcher from local repo.
  if [ ! -f "$ROOT_DIR/remote/prompt_watcher_v2.py" ]; then
    echo "Missing local watcher: $ROOT_DIR/remote/prompt_watcher_v2.py" >&2
    exit 1
  fi
  cat "$ROOT_DIR/remote/prompt_watcher_v2.py" | remote "cat > '$REMOTE_WATCHER' && chmod +x '$REMOTE_WATCHER'"
  remote "set -e; '$REMOTE_VENV_DIR/bin/python' -m py_compile '$REMOTE_WATCHER'"
}

start_watcher() {
  # Start inside zellij session to keep lifecycle visible in CodeLeader.
  # Use venv python explicitly.
  remote "set -e; zellij ls | grep -q \"$REMOTE_SESSION\"" || {
    echo "Remote zellij session not found: $REMOTE_SESSION" >&2
    exit 1
  }

  # Best-effort stop any existing watcher first (idempotent).
  remote "set +e; pids=\$(ps aux | grep -v grep | grep -F '$REMOTE_WATCHER' | awk '{print \$2}'); if [ -n \"\${pids:-}\" ]; then kill \$pids >/dev/null 2>&1; fi; exit 0" || true

  # Run in background + disown so it won't block the shell and won't be killed by job-control/SIGHUP.
  # Still writes logs into .codeleader/ only.
  remote "zellij --session '$REMOTE_SESSION' action write-chars \"$REMOTE_VENV_DIR/bin/python $REMOTE_WATCHER --url $WEBHOOK_URL --interval 0.8 >>$REMOTE_ERR 2>&1 & disown\" && zellij --session '$REMOTE_SESSION' action write 10"
}

stop_watcher() {
  # Idempotent stop: never fail if process is already gone.
  remote "set +e; pids=\$(ps aux | grep -v grep | grep -F '$REMOTE_WATCHER' | awk '{print \$2}'); if [ -n \"\${pids:-}\" ]; then kill \$pids >/dev/null 2>&1; fi; exit 0"
}

status_watcher() {
  remote "set -e; echo '--- watcher process'; ps aux | grep -v grep | grep -F '$REMOTE_WATCHER' || true; echo '--- err tail'; tail -n 20 '$REMOTE_ERR' 2>/dev/null || true; echo '--- venv'; '$REMOTE_VENV_DIR/bin/python' -V 2>/dev/null || echo 'venv missing'"
}

cmd="${1:-}"
case "$cmd" in
  --check)
    check_prereqs
    echo "OK"
    ;;
  --apply)
    check_prereqs
    ensure_dirs
    ensure_venv
    deploy_watcher
    echo "APPLIED"
    ;;
  --start)
    check_prereqs
    ensure_dirs
    ensure_venv
    deploy_watcher
    start_watcher
    echo "STARTED"
    ;;
  --stop)
    stop_watcher
    echo "STOPPED"
    ;;
  --status)
    status_watcher
    ;;
  *)
    usage
    exit 2
    ;;
esac
