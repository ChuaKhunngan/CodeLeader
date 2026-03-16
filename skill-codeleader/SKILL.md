---
name: codeleader
description: Operate a CodeLeader remote coding session through the project’s local Sentinel control plane. Use when you need to bring CodeLeader up, send exactly one prompt, inspect hook returns, fetch more tail context, or resolve approvals. This skill is for an agent unfamiliar with the project; prefer the shortest correct control path and avoid human-facing UI commands.
---

# CodeLeader

This skill is for a **cold-start agent** that has not seen this project before.

Goal: make the **next correct control action** with minimal ambiguity.

## What this skill is for

Use this skill when OpenClaw should act as **CodeLeader**:
- start or recreate the CodeLeader stack
- send exactly one prompt into the remote coding session
- read hook messages
- fetch more tail context when needed
- resolve approval blocks

Do not explain internals unless explicitly asked.
Do not optimize for completeness; optimize for the **correct next action**.

## Primary control model

CodeLeader has two planes:

1. **Startup plane**
   - local project launcher brings up Sentinel + tunnel + remote session/layout
2. **Control plane**
   - after startup, control the remote session through the **local Sentinel HTTP API**

For agent operation, the **control plane is the source of truth**.

## Required startup inputs

Before startup, collect these values:

1. `CODELEADER_REMOTE_SSH_HOST`
2. `CODELEADER_REMOTE_REPO_DIR`
3. `CODELEADER_OPENCLAW_SESSION_ID`

Optional only when fixed external push is explicitly wanted for this run:
4. `CODELEADER_NOTIFY_CMD`
5. `CODELEADER_NOTIFY_TIMEOUT_SECONDS`

## Startup path

Run from the project bundle directory:

```bash
export CODELEADER_REMOTE_SSH_HOST="<remote-host>"
export CODELEADER_REMOTE_REPO_DIR="<remote-repo-dir>"
export CODELEADER_OPENCLAW_SESSION_ID="<current-openclaw-session-id>"
# optional only if fixed-channel push is wanted
export CODELEADER_NOTIFY_CMD="<sender-command-reading-stdin>"
export CODELEADER_NOTIFY_TIMEOUT_SECONDS="15"

./scripts/start_codeleader_stack.sh --recreate
```

Use `--recreate` when re-binding, recovering, or when session/layout state may be stale.

## First action after startup

After startup, treat local Sentinel as the operator surface.

Default local Sentinel URL:

```text
http://127.0.0.1:8787
```

Default remote session id used by the stack:

```text
CodeLeader
```

## Send one prompt

Use this exact API shape:

```text
POST /api/v1/action/send_prompt?session_id=CodeLeader
body: {"prompt":"<your prompt>"}
```

Example:

```bash
curl -fsS -X POST 'http://127.0.0.1:8787/api/v1/action/send_prompt?session_id=CodeLeader' \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"<your prompt>"}'
```

Rule:
- send **exactly one** prompt
- then **stop immediately**
- wait for the next hook before deciding anything else

## Read more tail context

If current context is insufficient, fetch more before guessing.

```text
POST /api/v1/context/read_tail_lines
body: {"session_id":"CodeLeader","lines":60}
```

Example:

```bash
curl -fsS -X POST 'http://127.0.0.1:8787/api/v1/context/read_tail_lines' \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"CodeLeader","lines":60}'
```

Recommended sizes:
- 30
- 60
- 120

## Resolve approval

When blocked on approval, do not send a prompt.
Use:

```text
POST /api/v1/action/approve?session_id=CodeLeader
body: {"decision":"yes"}
```

Allowed decisions:
- `yes`
- `always`
- `no`

Example:

```bash
curl -fsS -X POST 'http://127.0.0.1:8787/api/v1/action/approve?session_id=CodeLeader' \
  -H 'Content-Type: application/json' \
  -d '{"decision":"yes"}'
```

After approval decision, stop and wait for the next hook.

## Hook decision table

### `AUTO_FLOW_COMPLETED`
Meaning:
- the remote round appears complete

Action:
- inspect the returned result first
- if needed, send **exactly one** next prompt
- then stop

### `AUTO_FLOW_BLOCKED_ON_APPROVAL`
Meaning:
- automation is blocked pending approval

Action:
- do **not** send a prompt
- either fetch more tail context or approve with one of `yes|always|no`
- then stop

### `HUMAN_INTERVENTION_STARTED`
Meaning:
- human takeover is in progress

Action:
- stop immediately
- do not send prompts
- wait for the next hook

### `HUMAN_INTERVENTION_READY_FOR_HOOK`
Meaning:
- human intervention likely finished

Action:
- inspect context
- if insufficient, fetch more tail lines
- only then decide whether to send **exactly one** prompt

## Cold-start recovery playbook

If you are entering a fresh session and need to verify control quickly:

1. collect required startup env vars
2. run `./scripts/start_codeleader_stack.sh --recreate`
3. send a minimal verification prompt through Sentinel
4. wait for hook return
5. only after successful hook return continue with normal single-flight operation

Minimal verification example:

```text
最小验证：如果你收到这条，请仅回复：SESSION_OK
```

## Absolute rules

1. **Single-flight only**
   - never queue multiple prompts
2. **Context first**
   - when cheap context is available, fetch it before guessing
3. **Approval boundary**
   - while blocked on approval, do not send prompts
4. **Hook-driven operation**
   - react to actual hook state, not imagined hidden state
5. **Agent path only**
   - prioritize the Sentinel HTTP control plane, not human-facing interaction paths

## What to avoid

Avoid:
- multi-step preplanning after sending a prompt
- sending another prompt before the next hook arrives
- guessing missing context when tail fetch is available
- exposing implementation details unless asked
- using human-oriented UI/view commands as the primary agent control path

## Summary

Think of CodeLeader as a remote execution lane controlled through local Sentinel.

Your job is:
1. bring the stack up
2. send one prompt
3. wait for hook
4. fetch more context if needed
5. either approve or send one next prompt
6. stop again
