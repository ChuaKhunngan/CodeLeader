---
name: codeleader
description: Operate CodeLeader as a remote coding control lane. Use when an agent needs to start the CodeLeader stack, send one prompt, react to hook messages, fetch more context, or resolve approvals. This skill is written for an agent unfamiliar with the project; keep to the narrow control path and avoid unrelated implementation details.
---

# CodeLeader

This skill is for an agent that has **not seen this project before**.

Read this as an **operation protocol**, not as developer documentation.

Your goal is simple:
- bring CodeLeader up when needed
- send **one** prompt
- wait for hook feedback
- make the **next** correct action only

## Use this skill when

Use this skill when you need to do any of these:
- start or recreate a CodeLeader run
- send a prompt into CodeLeader
- inspect a CodeLeader hook return
- fetch more tail context
- handle an approval block

## Critical clarification: OpenClaw session id

When startup asks for `CODELEADER_OPENCLAW_SESSION_ID`, it means the **actual OpenClaw session id**.

It does **not** mean:
- session key
- chat key
- routing key
- label
- channel recipient id
- any other lookalike identifier

Use the real session **id** value, typically a UUID-like string.

If you only have a session key and are not sure whether it is the same thing, assume it is **not** the right value until verified.

## Required inputs before startup

Collect these values:

1. `CODELEADER_REMOTE_SSH_HOST`
2. `CODELEADER_REMOTE_REPO_DIR`
3. `CODELEADER_OPENCLAW_SESSION_ID` = the real OpenClaw session **id**

Optional only if the run explicitly needs fixed external push:
4. `CODELEADER_NOTIFY_CMD`
5. `CODELEADER_NOTIFY_TIMEOUT_SECONDS`

## Startup action

Run the project startup script from the project directory:

```bash
export CODELEADER_REMOTE_SSH_HOST="<remote-host>"
export CODELEADER_REMOTE_REPO_DIR="<remote-repo-dir>"
export CODELEADER_OPENCLAW_SESSION_ID="<real-openclaw-session-id>"
./scripts/start_codeleader_stack.sh --recreate
```

Use `--recreate` when starting fresh, re-binding, or recovering from uncertain state.

If fixed external push is explicitly desired for this run, set the notify env vars before startup.
Otherwise leave them unset.

## Main control rule

After startup, operate CodeLeader through the local control API.

Do not invent alternative control paths.
Do not switch to unrelated human-oriented interaction paths.

## Send one prompt

Use this API:

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

After sending:
- stop immediately
- wait for the next hook

## Fetch more context

If current tail context is not enough, fetch more before deciding.

Use this API:

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

Reasonable line counts:
- 30
- 60
- 120

## Handle approval

If CodeLeader is blocked on approval, do **not** send a prompt.

Use this API instead:

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

After approval action:
- stop
- wait for the next hook

## Hook rules

### `AUTO_FLOW_COMPLETED`
Meaning:
- the remote round finished

What to do:
- inspect the returned result first
- if needed, send **exactly one** next prompt
- then stop

### `AUTO_FLOW_BLOCKED_ON_APPROVAL`
Meaning:
- approval is required

What to do:
- do **not** send a prompt
- either fetch more context or approve with `yes`, `always`, or `no`
- then stop

### `HUMAN_INTERVENTION_STARTED`
Meaning:
- human takeover is happening

What to do:
- stop immediately
- do not send prompts
- wait for the next hook

### `HUMAN_INTERVENTION_READY_FOR_HOOK`
Meaning:
- human intervention appears finished

What to do:
- inspect context
- if needed, fetch more tail lines
- only then decide whether to send **one** prompt

## Minimal recovery flow

If you are in a fresh session and need to confirm the setup works:

1. collect required inputs
2. run startup with `--recreate`
3. send a minimal verification prompt
4. wait for hook return
5. continue only after successful verification

Safe minimal verification prompt:

```text
最小验证：如果你收到这条，请仅回复：SESSION_OK
```

## Absolute rules

1. **One prompt at a time**
   - never queue multiple prompts
2. **Stop after action**
   - after sending a prompt, stop and wait for hook
   - after approval, stop and wait for hook
3. **Do not guess when context is cheap**
   - fetch more tail lines first
4. **Approval block means no prompt sending**
5. **Use the real OpenClaw session id**
   - not session key, not label, not recipient id
6. **Stay on the narrow control path**
   - avoid unrelated implementation details and alternative surfaces

## Avoid

Avoid:
- multi-step follow-up planning after sending a prompt
- sending another prompt before the next hook
- confusing session id with session key
- exposing internal architecture unless explicitly asked
- using irrelevant human-facing commands as agent instructions

## Summary

CodeLeader should be operated in a narrow loop:
1. start or recreate
2. send one prompt
3. wait for hook
4. fetch more context if needed
5. either approve or send one next prompt
6. stop again
