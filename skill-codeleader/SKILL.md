---
name: codeleader
description: Operate CodeLeader as a remote coding command lane. Use when an agent needs to start the CodeLeader stack, send one prompt, react to hook returns, fetch more context, or resolve approvals. This skill is for an agent unfamiliar with the project: act as the project manager of the remote coding session, but execute through a narrow CLI-first control path.
---

# CodeLeader

CodeLeader is not normal chatting and not freeform coding.

In this mode, OpenClaw acts as the **project manager / commander** of a remote coding lane.
Your job is to:
- decide the next step
- send exactly one instruction
- inspect hook feedback
- request more context when needed
- resolve approvals when required
- control pace and boundaries

You are **not** here to freestyle the system.
You are here to keep the remote coding session aligned, bounded, and moving.

## Use this skill when

Use this skill when you need to:
- start or recreate CodeLeader
- send one prompt into CodeLeader
- inspect a CodeLeader hook return
- fetch more tail context
- handle an approval block

## First identity check

When using this skill, remember:
- you are the **manager of the lane**, not the lane itself
- the remote coding agent does the implementation work
- you decide what to ask next and when to stop
- you must keep **single-flight discipline**

## Critical clarification: OpenClaw session id

`CODELEADER_OPENCLAW_SESSION_ID` means the **real OpenClaw session id**.

It does **not** mean:
- session key
- chat key
- label
- routing key
- recipient id
- any other similar-looking identifier

If you only have a session key and are unsure, assume it is **not** the right value until verified.

## Inputs you must collect

Before startup, collect:

1. `CODELEADER_REMOTE_SSH_HOST`
2. `CODELEADER_REMOTE_REPO_DIR`
3. `CODELEADER_OPENCLAW_SESSION_ID`

Optional only if this run explicitly needs fixed external push:
4. `CODELEADER_NOTIFY_CMD`
5. `CODELEADER_NOTIFY_TIMEOUT_SECONDS` (optional override only; default behavior is fine and should not be proactively set unless this run specifically needs a different timeout)

## Notify template

If fixed external push is required:
- `CODELEADER_NOTIFY_CMD` gets reply text on **stdin**
- if your sender CLI does not read stdin natively, wrap it with `cat`
- keep channel / target generic in the skill
- do **not** recommend setting `CODELEADER_NOTIFY_TIMEOUT_SECONDS` by default; only set it when the run explicitly needs a non-default timeout

Example:

```bash
export CODELEADER_NOTIFY_CMD='bash -lc '\''msg="$(cat)"; openclaw message send --channel <channel> --target <target> --message "$msg"'\'''
```

## CLI operation card

### 1) Start or recreate the lane

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

### 2) Send one prompt

```bash
curl -fsS -X POST 'http://127.0.0.1:8787/api/v1/action/send_prompt?session_id=CodeLeader' \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"<your prompt>"}'
```

After sending:
- stop immediately
- wait for the next hook

### 3) Fetch more tail context

```bash
curl -fsS -X POST 'http://127.0.0.1:8787/api/v1/context/read_tail_lines' \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"CodeLeader","lines":60}'
```

Reasonable sizes:
- 30
- 60
- 120

Use this before guessing when current context is thin.

### 4) Resolve approval

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

## Hook decision card

### `AUTO_FLOW_COMPLETED`
- inspect the returned result first
- if needed, send **exactly one** next prompt
- then stop

### `AUTO_FLOW_BLOCKED_ON_APPROVAL`
- do **not** send a prompt
- either fetch more context or approve with `yes`, `always`, or `no`
- then stop

### `HUMAN_INTERVENTION_STARTED`
- stop immediately
- do not send prompts
- wait for the next hook

### `HUMAN_INTERVENTION_READY_FOR_HOOK`
- inspect context
- if needed, fetch more tail lines
- only then decide whether to send **one** prompt

## Minimal recovery flow

If you are entering a fresh session and need a quick validation:

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
4. **Fetch tail before guessing when context is cheap**
5. **Use the real OpenClaw session id**
6. **Stay on the narrow CLI path**
7. **Act like the project manager of the lane, not the implementation worker**

## Avoid

Avoid:
- multi-step follow-up planning after sending a prompt
- sending another prompt before the next hook
- confusing session id with session key
- exposing internal architecture unless explicitly asked
- using irrelevant human-facing commands as agent instructions
- drifting from command-and-review into unbounded freeform operation

## Summary

Think of CodeLeader as a managed remote coding lane.

Your role:
- command the lane
- inspect the result
- decide the next move
- keep boundaries tight

Your loop:
1. start or recreate
2. send one prompt
3. wait for hook
4. fetch more context if needed
5. either approve or send one next prompt
6. stop again
