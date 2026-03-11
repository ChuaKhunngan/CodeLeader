# CodeLeader for OpenClaw

<table width="100%">
  <tr>
    <td align="left"><a href="README.zh-CN.md">中文版本</a></td>
    <td align="right"><a href="README_AGENT.md">Agent Edition</a></td>
  </tr>
</table>

<p align="center">
  <img src="assets/icon/openclaw-codeleader_icon_final_2048.jpg" alt="CodeLeader icon" width="220">
</p>

**CodeLeader is for people who want remote coding power without losing human control.**

Most coding-AI workflows still force a bad tradeoff:

- use coding AI tools like [Claude Code](https://www.anthropic.com/claude-code), [Codex](https://openai.com/codex/), [OpenCode](https://opencode.ai/), or [Gemini CLI](https://github.com/google-gemini/gemini-cli) directly, and still stay tied to the screen
- let agents run in the background, and lose visibility and control
- use desktop wrappers, and still end up supervising everything live
- enable dangerous permissions, and accept too much risk for long-running sessions
- switch between tools, and lose any consistent control model

**CodeLeader is built for the middle path.**

It keeps the **human** and **OpenClaw** on the **same layer**:
- looking at the same real working surface
- reacting through the same control loop
- deciding together when to hand work to a lower execution layer

That lower layer is a real remote coding session.

This matters because, in many real workflows, the code and compute are already remote — especially in research, shared servers, and remote compute environments. In those setups, the remote machine should stay the execution lane, not become the user's personal control plane.

So CodeLeader keeps:
- **OpenClaw local**
- **the coding agent remote**
- **the human in the loop**

Human takeover is built in.
A human can directly take over the remote coding agent conversation at any time, or inject a new instruction immediately. OpenClaw handles the decisions it can handle, and only escalates to the human when the situation actually needs human judgment. When the intervention is over, OpenClaw re-reads the current state, understands what changed, and continues from the new reality instead of blindly resuming an old plan.

## What this gives you

- **Less screen babysitting** — the human does not need to sit in front of the terminal for the entire run.
- **Less blind automation** — OpenClaw stays in the loop instead of disappearing into an opaque background process.
- **Cleaner handoff** — the human can step in, change direction, then let OpenClaw continue from the new state.
- **Lower token burn** — hook-driven observation means OpenClaw checks in when it needs to, instead of continuously polling the screen.
- **Safer long-running sessions** — explicit approval points are better suited than permanently over-privileged execution modes.
- **Terminal-native execution** — coding tools can stay where they are strongest: on the remote machine, inside a real terminal session.
- **One operational model across tools** — even if the lower-layer coding tools do not share one unified protocol, CodeLeader gives the upper workflow a more consistent control loop.

## What works now

- ✅ **Validated now:** [Claude Code](https://www.anthropic.com/claude-code)
- 🧭 **Planned next:** [Codex](https://openai.com/codex/), [OpenCode](https://opencode.ai/), [Gemini CLI](https://github.com/google-gemini/gemini-cli), and other terminal-native coding agents
- ✋ **Approvals stay controlled:** CodeLeader keeps approval decisions in the human/OpenClaw loop instead of silently pushing forward
- 🔄 **Human takeover is built in:** when a human steps in, automatic actions pause; when the human is done, OpenClaw continues from the new state
- 🖥️ **GUI:** desktop GUI is planned, but not the current focus
- 🧪 **Tested setup:** local **macOS** + remote **Ubuntu**
- ⚠️ **Not fully covered yet:** more platform combinations, deployment styles, and coding-agent combinations still need validation

## Requirements

### Local side

Before using CodeLeader, make sure:
- OpenClaw gateway is running on your local trusted machine
- your local machine can reach the remote machine over SSH

### Remote side

Before using CodeLeader, make sure the remote machine has:
- [Zellij](https://zellij.dev/) (`0.43.0`)
- [tmux](https://github.com/tmux/tmux/wiki)
- at least one coding agent CLI installed (for example [Claude Code](https://www.anthropic.com/claude-code), [Codex](https://openai.com/codex/), [OpenCode](https://opencode.ai/), or another terminal-native coding tool)
- a writable workdir for the project

## Quick start

### 1. Install the release bundle

Download the release bundle and unpack it into your OpenClaw skills directory.
The unpacked folder name should be:

```text
codeleader/
```

### 2. Ask OpenClaw to use CodeLeader

Then just tell OpenClaw what you want to build with CodeLeader.
For example:

```text
Use CodeLeader to build a Pomodoro timer app with task tracking.
```

OpenClaw should then collect any missing startup information and bring the stack up through the skill bundle.

### 3. Join the remote session when you want to collaborate live

When you want to step into the shared working surface with OpenClaw:

```bash
ssh <remote-host>
codeleader show
```

This opens the remote CodeLeader session directly.

## For developers: direct launcher usage

If you are operating the bundle directly, the main entrypoint is:

```bash
./scripts/start_codeleader_stack.sh --recreate
```

Typical required environment variables:

```bash
export CODELEADER_REMOTE_SSH_HOST="<remote-host>"
export CODELEADER_REMOTE_REPO_DIR="<remote-repo-dir>"
export CODELEADER_OPENCLAW_SESSION_ID="<current-openclaw-session-id>"
```

## Things to know

- If local port `8787` is still occupied after `down.sh`, startup stops and shows which process owns the port.
- To explicitly force-take the port, rerun with:

```bash
CODELEADER_FORCE_KILL_8787=1 ./scripts/start_codeleader_stack.sh --recreate
```

- If the remote workdir does not exist yet, the startup path will create it.
- The main launcher is the normal entrypoint; you usually do not need to run the lower-level helper scripts directly.
- The project currently favors a conservative control model: one prompt at a time, then wait for the next hook.

## License

MIT
