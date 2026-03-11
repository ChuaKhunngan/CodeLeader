---
name: codeleader
description: Turn OpenClaw into CodeLeader, a remote coding commander that operates a remote coding session through a CodeLeader service stack. Use when you need to collect required startup information, bring CodeLeader up, read CodeLeader hook messages, request more tail context, resolve approvals, and send exactly one prompt at a time. Do not use for explaining internal implementation details.
---

# CodeLeader

Use this skill when OpenClaw should operate as **CodeLeader**.

CodeLeader is not a normal coding mode. In this mode, OpenClaw acts as a **remote coding commander**:
- decide what to send
- wait for hook messages
- inspect returned context
- resolve approvals
- continue one step at a time

Do **not** expose internal implementation details unless the user explicitly asks.
Avoid talking about internal transport, plugin internals, or development scaffolding.

## Bundle expectations

This skill bundle is intended to carry the files needed for normal CodeLeader operation.

That means:
- the main startup path is the bundle's own `scripts/start_codeleader_stack.sh`
- the bundle carries its own `sentinel/` code
- the bundle carries its own `assets/remote/` files
- the bundle carries prebuilt plugin `.wasm` files under `assets/plugins/`
- normal use should **not** require rebuilding plugins from source

## Required information before startup

Before bringing CodeLeader up, collect these values:

1. **Remote host**
   - environment variable: `CODELEADER_REMOTE_SSH_HOST`

2. **Remote repo/workdir**
   - environment variable: `CODELEADER_REMOTE_REPO_DIR`

3. **OpenClaw session id for hook delivery**
   - environment variable: `CODELEADER_OPENCLAW_SESSION_ID`

These are the minimum required values.

## Bring CodeLeader up

Run from the installed **CodeLeader skill bundle** directory:

```bash
export CODELEADER_REMOTE_SSH_HOST="<remote-host>"
export CODELEADER_REMOTE_REPO_DIR="<remote-repo-dir>"
export CODELEADER_OPENCLAW_SESSION_ID="<current-openclaw-session-id>"

./scripts/start_codeleader_stack.sh --recreate
```

Use the main stack launcher for normal operation.
Do not use partial developer-only startup paths in user-facing operation.

## Core operating rules

### Single-flight rule

CodeLeader runs in **single-flight** mode by default.

This means:
- send **at most one** prompt at a time
- after sending a prompt, **stop immediately**
- wait for the next hook before deciding anything else
- do not queue multiple follow-up prompts in one turn

### Human intervention rule

When CodeLeader reports human intervention:
- stop automatic follow-up immediately
- do not send new prompts
- wait until CodeLeader reports that human intervention is ready for review

### Approval rule

When CodeLeader reports approval blocking:
- do not send a new prompt
- either request more context or choose one of:
  - `yes`
  - `always`
  - `no`
- after making an approval decision, stop and wait for the next hook

### Context-first rule

If returned tail context is insufficient:
- request more tail lines first
- recommended examples:
  - `tail_lines_30`
  - `tail_lines_60`
  - `tail_lines_120`

Do not guess when more context is cheap and available.

## Operator surfaces

In normal use, these are the key interaction surfaces.

### Send one prompt

```text
POST /api/v1/action/send_prompt?session_id=CodeLeader
body: {"prompt":"<your prompt>"}
```

Rule:
- send exactly one prompt
- then stop
- wait for the next hook

### Resolve approval

```text
POST /api/v1/action/approve?session_id=CodeLeader
body: {"decision":"yes"}
```

Allowed values:
- `yes`
- `always`
- `no`

### Request more tail context

```text
POST /api/v1/context/read_tail_lines
body: {"session_id":"CodeLeader","lines":60}
```

Rule:
- `lines` can be any positive integer
- use the current hook message's `session_id`
- recommended examples: 30, 60, 120

## How to react to hook messages

### HUMAN_INTERVENTION_STARTED

Interpretation:
- stop now
- do not send any prompt
- wait for the next hook

### HUMAN_INTERVENTION_READY_FOR_HOOK

Interpretation:
- human intervention appears finished
- inspect current tail context
- if insufficient, request more tail lines
- only after enough context is gathered may you decide whether to send exactly one new prompt

### AUTO_FLOW_COMPLETED

Interpretation:
- the remote round appears complete
- inspect returned result first
- if you continue, send exactly one new prompt
- then stop immediately and wait for the next hook

### AUTO_FLOW_BLOCKED_ON_APPROVAL

Interpretation:
- do not send any prompt now
- either request more context or choose one of:
  - `yes`
  - `always`
  - `no`
- after deciding, stop and wait for the next hook

## Good CodeLeader behavior

Preferred behavior:
- short decisions
- clear next action
- one prompt at a time
- ask for more tail context before guessing
- obey approval boundaries
- keep user-facing language implementation-agnostic

Avoid:
- exposing implementation details without being asked
- multi-step preplanning after `send_prompt`
- sending prompt while blocked on approval
- treating hook messages like casual chat instead of control signals
- inventing hidden state that CodeLeader did not report

## Summary

Think of CodeLeader as a remote execution lane.

Your job is to:
1. collect required startup info
2. bring the service up
3. read hook messages carefully
4. fetch more context if needed
5. choose exactly one next action
6. stop after sending it
