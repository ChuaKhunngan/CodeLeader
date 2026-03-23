#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LSOF_BIN="$(command -v lsof || true)"
if [[ -z "$LSOF_BIN" ]]; then
  echo "ERROR: lsof is required for local port conflict checks but was not found in PATH." >&2
  exit 2
fi
REMOTE_HOST="${CODELEADER_REMOTE_SSH_HOST:-}"
REMOTE_SESSION="${CODELEADER_REMOTE_ZELLIJ_SESSION:-CodeLeader}"
MODE="up"
if [[ "${1:-}" == "--recreate" ]]; then
  MODE="recreate"
fi

if [[ -z "$REMOTE_HOST" ]]; then
  echo "ERROR: CODELEADER_REMOTE_SSH_HOST is required."
  exit 2
fi
if [[ -z "${CODELEADER_REMOTE_REPO_DIR:-}" ]]; then
  echo "ERROR: CODELEADER_REMOTE_REPO_DIR is required."
  exit 2
fi
if [[ -z "${CODELEADER_OPENCLAW_SESSION_ID:-}" ]]; then
  echo "ERROR: CODELEADER_OPENCLAW_SESSION_ID is required."
  exit 2
fi

if [[ -n "${CODELEADER_REMOTE_HOME:-}" ]]; then
  REMOTE_HOME="$CODELEADER_REMOTE_HOME"
else
  REMOTE_HOME="$(ssh -o BatchMode=yes "$REMOTE_HOST" 'printf %s "$HOME"')"
fi

REMOTE_PLUGIN_DIR="$REMOTE_HOME/.codeleader/services/codeleader_plugins/current"
REMOTE_WASM="${CODELEADER_REMOTE_WASM_PATH:-$REMOTE_PLUGIN_DIR/codeleader_vision/target/wasm32-wasip1/release/codeleader_vision.wasm}"
REMOTE_GIT_WASM="${CODELEADER_REMOTE_GIT_WASM_PATH:-$REMOTE_PLUGIN_DIR/codeleader_git_status/target/wasm32-wasip1/release/codeleader_git_status.wasm}"
REMOTE_CONFIG_TEMPLATE="$ROOT_DIR/assets/remote/codeleader_session.kdl"
REMOTE_WRAPPER_TEMPLATE="$ROOT_DIR/assets/remote/codeleader"
REMOTE_CONFIG_DIR="$REMOTE_HOME/.codeleader/config"
REMOTE_CONFIG_PATH="$REMOTE_CONFIG_DIR/codeleader_session.kdl"
REMOTE_THEME_TEMPLATE="$ROOT_DIR/assets/remote/codeleader_theme.kdl"
REMOTE_THEME_DIR="$REMOTE_CONFIG_DIR/themes"
REMOTE_THEME_PATH="$REMOTE_THEME_DIR/codeleader_theme.kdl"
REMOTE_BIN_DIR="$REMOTE_HOME/.local/bin"
REMOTE_WRAPPER_PATH="$REMOTE_BIN_DIR/codeleader"
REMOTE_LAYOUT_DIR="$REMOTE_HOME/.codeleader/layouts"
REMOTE_LAYOUT_PATH="$REMOTE_LAYOUT_DIR/codeleader_tab1_3pane.kdl"
REMOTE_RUN_DIR="$REMOTE_HOME/.codeleader/run"
REMOTE_KEEPER_PIDFILE="$REMOTE_RUN_DIR/codeleader_keeper.pid"
CODEAI_DIR="$CODELEADER_REMOTE_REPO_DIR"
if [[ "$CODEAI_DIR" == "~/"* ]]; then
  CODEAI_DIR="$REMOTE_HOME/${CODEAI_DIR#\~/}"
fi
ssh -o BatchMode=yes "$REMOTE_HOST" "set -e; mkdir -p '$CODEAI_DIR'; cd '$CODEAI_DIR'"
CODEAI_CMD="${CODELEADER_CODEAI_CMD:-claude}"

CODEAI_CMD_RESOLVED="$(ssh -o BatchMode=yes "$REMOTE_HOST" "bash -lc 'command -v \"$CODEAI_CMD\" || true'" | tail -n 1)"
if [[ -z "$CODEAI_CMD_RESOLVED" ]]; then
  echo "ERROR: command '$CODEAI_CMD' not found on remote host ($REMOTE_HOST)." >&2
  exit 2
fi
CODEAI_BOOTSTRAP_RAW="export TERM=xterm-256color COLORTERM=truecolor; cd '$CODEAI_DIR' && exec $CODEAI_CMD_RESOLVED"

kdl_escape() {
  local s="$1"
  s=${s//\\/\\\\}
  s=${s//"/\\"}
  printf '%s' "$s"
}
CODEAI_BOOTSTRAP_ESCAPED="$(kdl_escape "$CODEAI_BOOTSTRAP_RAW")"
PLUGIN_WASM_ESCAPED="$(kdl_escape "$REMOTE_WASM")"
GIT_PLUGIN_WASM_ESCAPED="$(kdl_escape "$REMOTE_GIT_WASM")"
CODEAI_DIR_ESCAPED="$(kdl_escape "$CODEAI_DIR")"

CODEAI_BOOTSTRAP_SED="${CODEAI_BOOTSTRAP_ESCAPED//\\/\\\\}"
CODEAI_BOOTSTRAP_SED="${CODEAI_BOOTSTRAP_SED//&/\\&}"
PLUGIN_WASM_SED="${PLUGIN_WASM_ESCAPED//\\/\\\\}"
PLUGIN_WASM_SED="${PLUGIN_WASM_SED//&/\\&}"
GIT_PLUGIN_WASM_SED="${GIT_PLUGIN_WASM_ESCAPED//\\/\\\\}"
GIT_PLUGIN_WASM_SED="${GIT_PLUGIN_WASM_SED//&/\\&}"
CODEAI_DIR_SED="${CODEAI_DIR_ESCAPED//\\/\\\\}"
CODEAI_DIR_SED="${CODEAI_DIR_SED//&/\\&}"

cd "$ROOT_DIR"

check_local_sentinel_port_free() {
  local lsof_out
  if lsof_out=$("$LSOF_BIN" -nP -iTCP:8787 -sTCP:LISTEN 2>/dev/null); then
    if [[ -n "$lsof_out" ]]; then
      echo "ERROR: local port 8787 is occupied; refusing to start to avoid dual-sentinel confusion." >&2
      echo "$lsof_out" >&2
      exit 1
    fi
  fi
}

identify_local_8787_listener() {
  local pid cmd cwd
  pid="$("$LSOF_BIN" -nP -tiTCP:8787 -sTCP:LISTEN 2>/dev/null | head -n 1 || true)"
  if [[ -z "$pid" ]]; then
    return 1
  fi
  cmd="$(ps -p "$pid" -ww -o command= 2>/dev/null || true)"
  cwd="$("$LSOF_BIN" -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -n 1 || true)"
  printf '%s|%s|%s\n' "$pid" "$cwd" "$cmd"
}

handle_local_8787_conflict_after_down() {
  local listener pid cwd cmd force_kill
  listener="$(identify_local_8787_listener || true)"
  if [[ -z "$listener" ]]; then
    return 0
  fi

  pid="${listener%%|*}"
  listener="${listener#*|}"
  cwd="${listener%%|*}"
  cmd="${listener#*|}"
  force_kill="${CODELEADER_FORCE_KILL_8787:-0}"

  echo "ERROR: local port 8787 is still occupied after down.sh; refusing to continue." >&2
  echo "PID: $pid" >&2
  if [[ -n "$cwd" ]]; then
    echo "CWD: $cwd" >&2
  fi
  echo "COMMAND: $cmd" >&2

  if [[ "$force_kill" == "1" || "$force_kill" == "true" || "$force_kill" == "TRUE" || "$force_kill" == "yes" || "$force_kill" == "YES" ]]; then
    echo "WARN: CODELEADER_FORCE_KILL_8787 is enabled; force-stopping PID $pid." >&2
    kill "$pid" >/dev/null 2>&1 || true
    for i in {1..20}; do
      if ! kill -0 "$pid" 2>/dev/null; then
        return 0
      fi
      sleep 0.2
    done
    echo "ERROR: failed to stop PID $pid on port 8787." >&2
    return 1
  fi

  echo "Hint: rerun with CODELEADER_FORCE_KILL_8787=1 to force-stop the current 8787 listener before recreate." >&2
  return 1
}

if [[ "$MODE" == "recreate" ]]; then
  echo "[1/6] Stop local services"
  ./scripts/down.sh || true

  echo "[2/6] Stop remote watcher"
  CODELEADER_REMOTE_SSH_HOST="$REMOTE_HOST" ./scripts/bootstrap_remote.sh --stop || true

  echo "[2.5/6] Verify local sentinel port is free after down"
  handle_local_8787_conflict_after_down || exit 1
else
  echo "[1/6] Reuse local services when possible"
  echo "[2/6] Verify local sentinel port is free before start"
  check_local_sentinel_port_free
fi

echo "[3/6] Start local sentinel + tunnel"
NOTIFY_TIMEOUT_SECONDS_RAW="${CODELEADER_NOTIFY_TIMEOUT_SECONDS-}"
if [[ -n "$NOTIFY_TIMEOUT_SECONDS_RAW" ]]; then
  START_NOTIFY_TIMEOUT_SECONDS="$NOTIFY_TIMEOUT_SECONDS_RAW"
else
  START_NOTIFY_TIMEOUT_SECONDS="120"
fi
CODELEADER_ALLOW_REMOTE_EXEC="${CODELEADER_ALLOW_REMOTE_EXEC:-1}" CODELEADER_ENABLE_TUNNEL=1 CODELEADER_LOG_PROMPT_READY_HEARTBEAT=1 CODELEADER_REMOTE_SSH_HOST="$REMOTE_HOST" CODELEADER_NOTIFY_CMD="${CODELEADER_NOTIFY_CMD:-}" CODELEADER_NOTIFY_TIMEOUT_SECONDS="$START_NOTIFY_TIMEOUT_SECONDS" ./scripts/up.sh

echo "[4/6] Ensure remote plugin deploy/permission (watcher disabled)"
if ! CODELEADER_REMOTE_SSH_HOST="$REMOTE_HOST" CODELEADER_REMOTE_HOME="$REMOTE_HOME" START_WATCHER=0 ./scripts/remote_zero_bootstrap.sh > /tmp/codeleader_bootstrap.log 2>&1; then
  echo "ERROR: remote plugin deploy failed (step 4/6). Check /tmp/codeleader_bootstrap.log for details." >&2
  cat /tmp/codeleader_bootstrap.log >&2
  exit 1
fi

echo "[5/6] Ensure remote session/layout/config"
LAYOUT_TEMPLATE="$ROOT_DIR/assets/remote/codeleader_tab1_3pane.kdl"
[[ -f "$LAYOUT_TEMPLATE" ]] || { echo "Missing $LAYOUT_TEMPLATE"; exit 1; }
TMP_LAYOUT="$(mktemp -t codeleader-layout.XXXXXX.kdl)"
TMP_CONFIG="$(mktemp -t codeleader-config.XXXXXX.kdl)"
trap 'rm -f "$TMP_LAYOUT" "$TMP_CONFIG"' EXIT
sed -e "s|__PLUGIN_WASM_PATH__|$PLUGIN_WASM_SED|g" \
    -e "s|__GIT_PLUGIN_WASM_PATH__|$GIT_PLUGIN_WASM_SED|g" \
    -e "s|__CODEAI_DIR__|$CODEAI_DIR_SED|g" \
    -e "s|__REMOTE_HOST__|$REMOTE_HOST|g" \
    -e "s|__CODEAI_BOOTSTRAP__|$CODEAI_BOOTSTRAP_SED|g" \
    "$LAYOUT_TEMPLATE" > "$TMP_LAYOUT"
sed -e "s|__THEME_DIR__|$REMOTE_THEME_DIR|g" \
    "$REMOTE_CONFIG_TEMPLATE" > "$TMP_CONFIG"

cat "$TMP_LAYOUT" | ssh -o BatchMode=yes "$REMOTE_HOST" "set -e; mkdir -p '$REMOTE_LAYOUT_DIR'; cat > '$REMOTE_LAYOUT_PATH'"
cat "$TMP_CONFIG" | ssh -o BatchMode=yes "$REMOTE_HOST" "set -e; mkdir -p '$REMOTE_CONFIG_DIR'; cat > '$REMOTE_CONFIG_PATH'"
cat "$REMOTE_THEME_TEMPLATE" | ssh -o BatchMode=yes "$REMOTE_HOST" "set -e; mkdir -p '$REMOTE_THEME_DIR'; cat > '$REMOTE_THEME_PATH'"
cat "$REMOTE_WRAPPER_TEMPLATE" | ssh -o BatchMode=yes "$REMOTE_HOST" "set -e; mkdir -p '$REMOTE_BIN_DIR'; cat > '$REMOTE_WRAPPER_PATH'; chmod +x '$REMOTE_WRAPPER_PATH'"

if [[ "$MODE" == "recreate" ]]; then
  ssh -o BatchMode=yes "$REMOTE_HOST" "set -e
    mkdir -p '$REMOTE_RUN_DIR'
    if [[ -f '$REMOTE_KEEPER_PIDFILE' ]]; then
      old_pid=\$(cat '$REMOTE_KEEPER_PIDFILE' || true)
      if [[ -n \"\$old_pid\" ]] && kill -0 \"\$old_pid\" 2>/dev/null; then kill \"\$old_pid\" >/dev/null 2>&1 || true; fi
      rm -f '$REMOTE_KEEPER_PIDFILE'
    fi
    zellij delete-session '$REMOTE_SESSION' --force >/dev/null 2>&1 || true
    sleep 2
    zellij --config '$REMOTE_CONFIG_PATH' --new-session-with-layout '$REMOTE_LAYOUT_PATH' --session '$REMOTE_SESSION' -d >/dev/null 2>&1 || true
    sleep 2
  "
else
  ssh -o BatchMode=yes "$REMOTE_HOST" "set -e
    mkdir -p '$REMOTE_RUN_DIR'
    zellij list-sessions 2>/dev/null | grep -q '^$REMOTE_SESSION' || \
      zellij --config '$REMOTE_CONFIG_PATH' --new-session-with-layout '$REMOTE_LAYOUT_PATH' --session '$REMOTE_SESSION' -d >/dev/null 2>&1 || true
    sleep 2
  "
fi

ssh -o BatchMode=yes "$REMOTE_HOST" "set -e
  mkdir -p '$REMOTE_RUN_DIR'
  if [[ -f '$REMOTE_KEEPER_PIDFILE' ]]; then
    keeper_pid=\$(cat '$REMOTE_KEEPER_PIDFILE' || true)
    if [[ -n \"\$keeper_pid\" ]] && ! kill -0 \"\$keeper_pid\" 2>/dev/null; then rm -f '$REMOTE_KEEPER_PIDFILE'; fi
  fi
  if [[ ! -f '$REMOTE_KEEPER_PIDFILE' ]]; then
    tmux kill-session -t codeleader-keeper >/dev/null 2>&1 || true
    tmux -f /dev/null new-session -d -x 400 -y 120 -s codeleader-keeper \"env TERM=xterm-256color COLORTERM=truecolor zellij --config '$REMOTE_CONFIG_PATH' attach '$REMOTE_SESSION'\"
    tmux_pid=\$(tmux -f /dev/null display-message -p -t codeleader-keeper '#{pid}' 2>/dev/null || true)
    if [[ -n \"\$tmux_pid\" ]]; then echo \"\$tmux_pid\" > '$REMOTE_KEEPER_PIDFILE'; fi
  fi
"

LAYOUT_OK=1
if ! ssh -o BatchMode=yes "$REMOTE_HOST" "zellij --session '$REMOTE_SESSION' action dump-layout > /tmp/codeleader_layout_check.kdl && grep -q 'name=\"CodingAI\"' /tmp/codeleader_layout_check.kdl && grep -q 'name=\"CodeLeader Status\"' /tmp/codeleader_layout_check.kdl && grep -q 'name=\"Git Status\"' /tmp/codeleader_layout_check.kdl"; then
  LAYOUT_OK=0
fi

if [[ "$MODE" == "up" && "$LAYOUT_OK" != "1" ]]; then
  echo "WARN: session exists but 3-pane layout could not be verified hot. Please run --recreate to fully rebuild." >&2
fi
if [[ "$MODE" == "recreate" && "$LAYOUT_OK" != "1" ]]; then
  echo "ERROR: recreate completed but 3-pane layout verification failed." >&2
  exit 1
fi

echo "[6/6] Quick checks"
curl -fsS "http://127.0.0.1:8787/health" >/dev/null && echo "- local sentinel health: OK"
if ssh -o BatchMode=yes "$REMOTE_HOST" "if [[ -f '$REMOTE_KEEPER_PIDFILE' ]]; then keeper_pid=\$(cat '$REMOTE_KEEPER_PIDFILE' || true); [[ -n \"\$keeper_pid\" ]] && kill -0 \"\$keeper_pid\" 2>/dev/null; else exit 1; fi"; then
  echo "- keeper client: OK"
else
  echo "WARN: keeper client missing/unhealthy; run --recreate if send_prompt does not work" >&2
fi

echo "- performing local handshake with Sentinel..."
HANDSHAKE_OK=0
for i in {1..20}; do
  # Perform a handshake by starting/re-starting the session in the local Sentinel state machine
  # We test the /api/v1/session/start endpoint. It returns HTTP 200 if fresh,
  # or HTTP 403 if it was already started (which is also fine, meaning Sentinel is alive and knows the session).
  HTTP_RESPONSE=$(curl -s -w "HTTPSTATUS:%{http_code}" -X POST "http://127.0.0.1:8787/api/v1/session/start" \
       -H "Content-Type: application/json" \
       -d "{\"session_id\": \"$REMOTE_SESSION\"}")
  
  # extract body and status
  HTTP_BODY=$(echo "$HTTP_RESPONSE" | sed -E 's/HTTPSTATUS\:[0-9]{3}$//')
  HTTP_STATUS=$(echo "$HTTP_RESPONSE" | tr -d '\n' | sed -E 's/.*HTTPSTATUS:([0-9]{3})$/\1/')

  if [[ "$HTTP_STATUS" == "200" ]]; then
    HANDSHAKE_OK=1
    echo "  handshake successful (started)."
    break
  elif [[ "$HTTP_STATUS" == "403" && "$HTTP_BODY" == *"start not allowed in state"* ]]; then
    HANDSHAKE_OK=1
    echo "  handshake successful (already running)."
    break
  fi
  sleep 1
done

if [[ "$HANDSHAKE_OK" != "1" ]]; then
  echo "ERROR: Local Sentinel handshake failed. Sentinel might not be ready or tunneling failed." >&2
  exit 1
fi

echo
printf '%s\n' "========================================"
printf '%s\n' "✅ CODELEADER STACK READY"
printf '%s\n' "========================================"
printf 'Mode                : %s\n' "$MODE"
printf 'Remote Host         : %s\n' "$REMOTE_HOST"
printf 'User Home Dir       : %s\n' "$REMOTE_HOME"
printf 'Project Root        : %s\n' "$CODEAI_DIR"
if [[ "$CODEAI_CMD" == *"claude"* ]]; then
  printf 'Coding AI           : Claude Code (cmd: %s)\n' "$CODEAI_CMD_RESOLVED"
elif [[ "$CODEAI_CMD" == *"cursor"* ]]; then
  printf 'Coding AI           : Cursor (cmd: %s)\n' "$CODEAI_CMD_RESOLVED"
else
  printf 'Coding AI           : %s\n' "$CODEAI_CMD_RESOLVED"
fi
printf 'Show (for human)    : 1) ssh %s\n' "$REMOTE_HOST"
printf '                      2) codeleader show\n'
printf '%s\n' "----------------------------------------"
printf '%s\n' "⚠️  First-time repo trust note:"
printf '%s\n' "   If Claude Code asks to trust this folder in CodingAI pane, choose 'yes'."
printf '%s\n' "========================================"
