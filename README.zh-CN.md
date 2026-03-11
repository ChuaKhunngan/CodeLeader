# CodeLeader for OpenClaw

[English version](README.md)

<p align="center">
  <img src="assets/icon/openclaw-codeleader_icon_final_2048.jpg" alt="CodeLeader 图标" width="220">
</p>

**CodeLeader 想解决的是这样的问题：你想用 OpenClaw 指挥远程 coding agent 干活，但又不想失去对过程的控制。**

现在大多数 coding AI 工作流，仍然绕不开一个很别扭的二选一：

- 直接用 [Claude Code](https://www.anthropic.com/claude-code)、[Codex](https://openai.com/codex/)、[OpenCode](https://opencode.ai/) 或 [Gemini CLI](https://github.com/google-gemini/gemini-cli)，能力很强，但人还是得一直盯着屏幕
- 让 agent 在后台跑，虽然省事，但人类会逐渐失去可见性和控制权
- 套一层桌面包装，看起来更友好，但最后还是得坐在电脑前全程盯着它
- 开启危险权限模式，短时间内很方便，但不适合长时间运行的真实项目
- 在不同工具之间切换时，操作方式、审批方式、心智模型都不统一

**CodeLeader 解决的，就是这中间缺掉的控制环。**

它把 **人类** 和 **OpenClaw** 留在**同一层**：
- 看同一个真实工作面
- 走同一条控制流程
- 一起决定什么时候把工作交给下层执行层

而下层执行层，就是一个真实的远程 coding session。

这点很重要。因为在很多真实工作流里，代码和算力本来就在远端——尤其是科研、共享服务器和远程算力环境里。在这些场景下，远端机器应该承担执行职责，而不应该变成用户的个人控制平面。

所以 CodeLeader 的分工很明确：
- **OpenClaw 留在本地**
- **coding agent 跑在远端**
- **人类始终在环路中**

而且，人类可以随时介入。
CodeLeader 内建了人类接管能力：你可以随时接管远端 coding agent 的对话，也可以随时插入新的指令。OpenClaw 会优先处理它能处理的决策，只有在确实需要人类判断时才把问题交回来；而当人类介入结束后，OpenClaw 会重新读取当前状态、理解刚刚发生了什么，再基于新的现实继续推进，而不是机械地恢复旧计划。

## 你能得到什么

- **更少盯屏** —— 不需要在整个运行过程中一直守在终端前
- **更少盲目后台化** —— OpenClaw 不会消失在一个不透明的后台流程里，而是持续留在控制环中
- **更自然的 handoff** —— 人类可以中途接手、改方向，再把控制权交还给 OpenClaw
- **更低的 token 消耗** —— hook 驱动的观察方式让 OpenClaw 在真正需要时才介入，而不是持续轮询屏幕
- **更适合长时间运行** —— 显式审批点比长期开启高权限危险模式更稳妥
- **保留 terminal-native 执行优势** —— coding 工具仍然运行在它们最擅长的地方：远端真实终端里
- **更统一的操作模型** —— 即使底层 coding 工具协议不统一，CodeLeader 也能让上层控制流程尽量保持一致

## 当前已经支持到哪里

- ✅ **当前已验证路径：** [Claude Code](https://www.anthropic.com/claude-code)
- 🧭 **下一步计划支持：** [Codex](https://openai.com/codex/)、[OpenCode](https://opencode.ai/)、[Gemini CLI](https://github.com/google-gemini/gemini-cli/) 以及其他 terminal-native coding agent
- ✋ **审批始终受控：** CodeLeader 会把审批决策保留在人类 / OpenClaw 的控制环里，而不是静默向前推进
- 🔄 **内建人类接管：** 人类介入时自动动作会暂停；介入结束后，OpenClaw 会从新的状态继续推进
- 🖥️ **GUI 方向：** 桌面 GUI 正在规划，但不是当前重点
- 🧪 **当前测试环境：** 本地 **macOS** + 远端 **Ubuntu**
- ⚠️ **尚未完整覆盖：** 更多平台组合、部署方式、coding agent 组合仍需继续验证

## 使用前准备

### 本地侧

在使用 CodeLeader 前，请确保：
- 本地可信机器上正在运行 OpenClaw gateway
- 本地机器能够通过 SSH 连接远端机器

### 远端侧

在使用 CodeLeader 前，请确保远端机器具备：
- [Zellij](https://zellij.dev/)（`0.43.0`）
- [tmux](https://github.com/tmux/tmux/wiki)
- 至少一种 coding agent CLI（例如 [Claude Code](https://www.anthropic.com/claude-code)、[Codex](https://openai.com/codex/)、[OpenCode](https://opencode.ai/) 或其他 terminal-native coding tool）
- 一个可写的项目工作目录

## 快速开始

### 1. 安装 release bundle

下载 release 包，并把它解压到你的 OpenClaw skills 目录中。
解压后的文件夹名称应保持为：

```text
codeleader/
```

### 2. 直接告诉 OpenClaw 使用 CodeLeader

然后直接告诉 OpenClaw，你希望 CodeLeader 做什么。
例如：

```text
Use CodeLeader to build a Pomodoro timer app with task tracking.
```

OpenClaw 会在需要时自动补全缺失的启动信息，并通过这个 skill bundle 拉起整套系统。

### 3. 需要实时协作时，进入远端 session

如果你想亲自进入那个共享工作面，与 OpenClaw 一起协作：

```bash
ssh <remote-host>
codeleader show
```

这会直接打开远端的 CodeLeader session。

## 给开发者：直接使用 launcher

如果你想直接操作这个 bundle，本地主入口是：

```bash
./scripts/start_codeleader_stack.sh --recreate
```

通常需要的环境变量有：

```bash
export CODELEADER_REMOTE_SSH_HOST="<remote-host>"
export CODELEADER_REMOTE_REPO_DIR="<remote-repo-dir>"
export CODELEADER_OPENCLAW_SESSION_ID="<current-openclaw-session-id>"
```

## 需要知道的事

- 如果执行 `down.sh` 之后本地 `8787` 端口仍被占用，启动流程会停止，并显示当前占用该端口的进程
- 如果你要显式强制接管该端口，可以这样重跑：

```bash
CODELEADER_FORCE_KILL_8787=1 ./scripts/start_codeleader_stack.sh --recreate
```

- 如果远端工作目录不存在，启动流程会自动创建它
- 正常使用时，主入口就是 launcher；通常不需要手动调用更底层的 helper scripts
- 当前默认采用保守控制模型：一次只推进一个 prompt，然后等待下一次 hook

## License

MIT
