---
name: codeleader
description: Operate CodeLeader through a narrow CLI-first control path. Use when an agent needs to start the CodeLeader stack, send one prompt, react to hook returns, fetch more context, or resolve approvals. This skill is for an agent unfamiliar with the project: prefer the provided commands, keep one-action-at-a-time discipline, and avoid broad implementation assumptions.
---

# CodeLeader

This skill is for an agent that has **not seen this project before**.

Treat CodeLeader as a **single-flight remote coding lane**.
Your job is not to explore the system. Your job is to:

1. start the lane
2. send **one** prompt
3. wait for hook feedback
4. make **one** next decision
5. stop again

## Use this skill when

Use this skill when you need to do any of these:
- start or recreate CodeLeader
- send one prompt into CodeLeader
- inspect a CodeLeader hook return
- fetch more tail context
- handle an approval block

## Critical clarification: OpenClaw session id

`CODELEADER_OPENCLAW_SESSION_ID` means the **real OpenClaw session id**.

It does **not** mean:
- session key
- chat key
- label
- routing key
- recipient id
- any other lookalike identifier

If you only have a session key and are unsure, assume it is **not** the right value until verified.

## Required inputs

Collect these values before startup:

1. `CODELEADER_REMOTE_SSH_HOST`
2. `CODELEADER_REMOTE_REPO_DIR`
3. `CODELEADER_OPENCLAW_SESSION_ID`

Optional only if the run explicitly needs fixed external push:
4. `CODELEADER_NOTIFY_CMD`
5. `CODELEADER_NOTIFY_TIMEOUT_SECONDS`

## Notify command template

If fixed external push is wanted for this run, remember:
- `CODELEADER_NOTIFY_CMD` receives reply text on **stdin**
- if your sender CLI does not read message text from stdin by itself, wrap it with `cat`
- keep channel / target generic in the skill; do not hardcode private recipient details

Generic template:

```bash
export CODELEADER_NOTIFY_CMD='bash -lc '\''msg="$(cat)"; openclaw message send --channel <channel> --target <target> --message "$msg"'\'''
```

## Startup

Run from the project directory:

```bash
export CODELEADER_REMOTE_SSH_HOST="<remote-host>"
export CODELEADER_REMOTE_REPO_DIR="<remote-repo-dir>"
export CODELEADER_OPENCLAW_SESSION_ID="<real-openclaw-session-id>"
./scripts/start_codeleader_stack.sh --recreate
```

Use `--recreate` when:
- starting fresh
- re-binding to a different session id
- recovering from uncertain state

If fixed external push is needed, export the notify vars before startup.

## Main operating surface

After startup, use the local CLI-friendly control path below.
Do not invent alternate paths.
Do not switch to irrelevant human-facing commands.

### Send one prompt

```bash
curl -fsS -X POST 'http://127.0.0.1:8787/api/v1/action/send_prompt?session_id=CodeLeader' \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"<your prompt>"}'
```

After sending:
- stop immediately
- wait for the next hook

### Fetch more tail context

```bash
curl -fsS -X POST 'http://127.0.0.1:8787/api/v1/context/read_tail_lines' \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"CodeLeader","lines":60}'
```

Reasonable sizes:
- 30
- 60
- 120

When context is cheap, fetch it before guessing.

### Resolve approval

If blocked on approval, do **not** send a prompt.
Use:

```bash
curl -fsS -X POST 'http://127.0.0.1:8787/api/v1/action/approve?session_id=CodeLeader' \
  -H 'Content-Type: application/json' \
  -d '{"decision":"yes"}'
```

Allowed decisions:
- `yes`
- `always`
- `no`

After approval:
- stop
- wait for the next hook

## Hook rules

### `AUTO_FLOW_COMPLETED`
Action:
- inspect the returned result first
- if needed, send **exactly one** next prompt
- then stop

### `AUTO_FLOW_BLOCKED_ON_APPROVAL`
Action:
- do **not** send a prompt
- either fetch more context or approve with `yes`, `always`, or `no`
- then stop

### `HUMAN_INTERVENTION_STARTED`
Action:
- stop immediately
- do not send prompts
- wait for the next hook

### `HUMAN_INTERVENTION_READY_FOR_HOOK`
Action:
- inspect context
- if needed, fetch more tail lines
- only then decide whether to send **one** prompt

## Minimal recovery flow

If you enter a fresh session and need a quick validation:

1. collect required inputs
2. run startup with `--recreate`
3. send a minimal verification prompt
4. wait for hook return
5. continue only after successful verification

Minimal verification prompt:

```text
最小验证：如果你收到这条，请仅回复：SESSION_OK
```

## Absolute rules

1. **One prompt at a time**
2. **Stop after each action**
3. **Approval block means no prompt sending**
4. **Do not guess when tail context is cheap**
5. **Use the real OpenClaw session id**
6. **Stay on the narrow CLI path**

## Avoid

Avoid:
- multi-step follow-up planning after sending a prompt
- sending another prompt before the next hook
- confusing session id with session key
- exposing internal architecture unless explicitly asked
- using irrelevant human-facing commands as agent instructions

## Summary

CodeLeader should be operated as a narrow CLI loop:

1. start or recreate
2. send one prompt
3. wait for hook
4. fetch more context if needed
5. either approve or send one next prompt
6. stop again
