#!/usr/bin/env bash
set -euo pipefail

# CodeLeader remote zero-bootstrap (idempotent, versioned, service-root mode)
#
# Remote service root (single source on device): ~/.codeleader
# Reuse existing installation unless:
#   - local plugin source hash changed
#   - remote wasm missing/broken
#   - FORCE_REINSTALL=1

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
REMOTE_USER_DIR="${CODELEADER_REMOTE_USER_DIR:-$REMOTE_USER_HOME/codeleader}"
REMOTE_SESSION="${CODELEADER_REMOTE_ZELLIJ_SESSION:-CodeLeader}"
START_WATCHER="${START_WATCHER:-1}"
FORCE_REINSTALL="${FORCE_REINSTALL:-0}"

# New canonical remote service root (user-scoped, repo-independent)
REMOTE_SERVICE_ROOT="${CODELEADER_REMOTE_SERVICE_ROOT:-$REMOTE_USER_HOME/.codeleader}"
REMOTE_PLUGIN_DIR_REL="services/codeleader_plugins/current"
REMOTE_PLUGIN_DIR="$REMOTE_SERVICE_ROOT/$REMOTE_PLUGIN_DIR_REL"
REMOTE_WASM_PATH="$REMOTE_PLUGIN_DIR/codeleader_vision/target/wasm32-wasip1/release/codeleader_vision.wasm"
REMOTE_GIT_WASM_PATH="$REMOTE_PLUGIN_DIR/codeleader_git_status/target/wasm32-wasip1/release/codeleader_git_status.wasm"
REMOTE_META_DIR="$REMOTE_SERVICE_ROOT/meta"
REMOTE_VERSION_FILE="$REMOTE_META_DIR/codeleader_plugins.sha256"

LOCAL_PLUGIN_SRC="$ROOT_DIR/plugins"

ssh_remote() {
  ssh -o BatchMode=yes "$REMOTE_HOST" "$@"
}

echo "[0/9] Preflight local files"
[[ -d "$LOCAL_PLUGIN_SRC" ]] || { echo "Missing local plugin source: $LOCAL_PLUGIN_SRC" >&2; exit 1; }

LOCAL_HASH="$(cd "$LOCAL_PLUGIN_SRC" && find . -type f ! -path './target/*' -print0 | sort -z | xargs -0 shasum -a 256 | shasum -a 256 | awk '{print $1}')"
echo "Local plugin source hash: $LOCAL_HASH"

echo "[1/9] Ensure remote directories (~/.codeleader canonical)"
ssh_remote "set -e; mkdir -p '$REMOTE_USER_DIR' '$REMOTE_SERVICE_ROOT' '$REMOTE_META_DIR' '$REMOTE_PLUGIN_DIR'"

echo "[2/9] Decide reuse vs reinstall"
REMOTE_HASH="$(ssh_remote "set -e; [ -f '$REMOTE_VERSION_FILE' ] && cat '$REMOTE_VERSION_FILE' || true")"
NEED_INSTALL=0
REASON="reuse-ok"
if [[ "$FORCE_REINSTALL" == "1" || "$FORCE_REINSTALL" == "true" || "$FORCE_REINSTALL" == "TRUE" ]]; then
  NEED_INSTALL=1
  REASON="force-reinstall"
elif [[ -z "$REMOTE_HASH" ]]; then
  NEED_INSTALL=1
  REASON="remote-version-missing"
elif [[ "$REMOTE_HASH" != "$LOCAL_HASH" ]]; then
  NEED_INSTALL=1
  REASON="version-changed"
else
  # hash same: check wasm integrity quickly
  if ! ssh_remote "set -e; [ -f '$REMOTE_WASM_PATH' ] && [ -f '$REMOTE_GIT_WASM_PATH' ]; file '$REMOTE_WASM_PATH' | grep -qi WebAssembly; file '$REMOTE_GIT_WASM_PATH' | grep -qi WebAssembly" >/dev/null 2>&1; then
    NEED_INSTALL=1
    REASON="wasm-missing-or-broken"
  fi
fi

echo "Decision: NEED_INSTALL=$NEED_INSTALL ($REASON)"

if [[ "$NEED_INSTALL" == "1" ]]; then
  echo "[3/9] Ensure rustup/cargo (user-local; install path only)"
  ssh_remote "set -e; \
    if ! command -v rustup >/dev/null 2>&1; then \
      curl https://sh.rustup.rs -sSf | sh -s -- -y --no-modify-path; \
    fi; \
    export PATH=\"\$HOME/.cargo/bin:\$PATH\"; \
    rustup toolchain install stable --profile minimal >/dev/null 2>&1 || true; \
    rustup default stable >/dev/null 2>&1 || true; \
    rustup target add wasm32-wasip1 >/dev/null 2>&1 || true; \
    rustc --version; cargo --version"

  echo "[4/9] Sync plugin source -> remote service root"
  tar -C "$LOCAL_PLUGIN_SRC" -cf - . | ssh_remote "set -e; rm -rf '$REMOTE_PLUGIN_DIR'; mkdir -p '$REMOTE_PLUGIN_DIR'; tar -C '$REMOTE_PLUGIN_DIR' -xf -"

  echo "[5/9] Build plugin wasm"
  ssh_remote "set -e; export PATH=\"\$HOME/.cargo/bin:\$PATH\"; \
    cd '$REMOTE_PLUGIN_DIR/codeleader_vision'; cargo build --target wasm32-wasip1 --release; ls -lh '$REMOTE_WASM_PATH'; \
    cd '$REMOTE_PLUGIN_DIR/codeleader_git_status'; cargo build --target wasm32-wasip1 --release; ls -lh '$REMOTE_GIT_WASM_PATH'"

  echo "[6/9] Record installed version hash"
  ssh_remote "set -e; printf '%s' '$LOCAL_HASH' > '$REMOTE_VERSION_FILE'; cat '$REMOTE_VERSION_FILE'"
else
  echo "[3-6/9] Reuse existing remote service (skip rust/sync/build)"
fi

echo "[7/9] Pre-authorize plugin permission (ReadApplicationState & RunCommands)"
ssh_remote "set -e; mkdir -p ~/.cache/zellij; touch ~/.cache/zellij/permissions.kdl; \
python3 - <<'PY'
from pathlib import Path
perm = Path.home()/'.cache'/'zellij'/'permissions.kdl'
wasm_vision = '$REMOTE_WASM_PATH'
wasm_git = '$REMOTE_GIT_WASM_PATH'
content = perm.read_text(encoding='utf-8') if perm.exists() else ''
block1 = f'\"{wasm_vision}\" {{\n    ReadApplicationState\n    RunCommands\n}}\n'
block2 = f'\"{wasm_git}\" {{\n    RunCommands\n}}\n'

if f'\"{wasm_vision}\"' not in content:
    if content and not content.endswith('\n'): content += '\n'
    content += block1
if f'\"{wasm_git}\"' not in content:
    if content and not content.endswith('\n'): content += '\n'
    content += block2

perm.write_text(content, encoding='utf-8')
print('permissions patched:', perm)
PY"

echo "[8/9] Ensure zellij session exists"
ssh_remote "set -e; command -v zellij >/dev/null; zellij list-sessions 2>/dev/null | grep -q '$REMOTE_SESSION' || zellij attach --create-background '$REMOTE_SESSION' >/dev/null 2>&1"

echo "[9/9] Deploy watcher via bootstrap_remote.sh"
if [[ "$START_WATCHER" == "1" || "$START_WATCHER" == "true" || "$START_WATCHER" == "TRUE" ]]; then
  CODELEADER_REMOTE_SSH_HOST="$REMOTE_HOST" \
  CODELEADER_REMOTE_USER_DIR="$REMOTE_USER_DIR" \
  CODELEADER_REMOTE_HOME="$REMOTE_USER_HOME" \
  CODELEADER_REMOTE_ZELLIJ_SESSION="$REMOTE_SESSION" \
  "$ROOT_DIR/scripts/bootstrap_remote.sh" --start
else
  CODELEADER_REMOTE_SSH_HOST="$REMOTE_HOST" \
  CODELEADER_REMOTE_USER_DIR="$REMOTE_USER_DIR" \
  CODELEADER_REMOTE_HOME="$REMOTE_USER_HOME" \
  CODELEADER_REMOTE_ZELLIJ_SESSION="$REMOTE_SESSION" \
  "$ROOT_DIR/scripts/bootstrap_remote.sh" --apply
fi

echo "DONE: zero-bootstrap complete"
echo "Remote service root: $REMOTE_SERVICE_ROOT"
echo "Remote plugin wasm: $REMOTE_WASM_PATH"
echo "Load in zellij: ZELLIJ_SESSION_NAME=$REMOTE_SESSION zellij action new-pane --plugin file:$REMOTE_WASM_PATH"
