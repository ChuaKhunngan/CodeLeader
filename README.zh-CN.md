# CodeLeader for OpenClaw

<table width="100%">
  <tr>
    <td align="left"><a href="README.md">English version</a></td>
    <td align="right"><a href="README_AGENT.zh-CN.md">Agent 版</a></td>
  </tr>
</table>

<p align="center">
  <img src="assets/icon/openclaw-codeleader_icon_final_2048.jpg" alt="CodeLeader 图标" width="220">
</p>

**CodeLeader 让 OpenClaw 不只是派发任务，而是像项目经理一样持续管理远端 terminal-native coding AI tools，例如 Claude Code、Codex、OpenCode、Gemini CLI：跟进执行进度、纠正偏航、处理审批、汇报状态，并只在必要时把问题升级给人类。**

> **这里的工具指的是运行在真实终端 session 里的 coding agent，而不是 VS Code 这类 IDE。远端 coding tools 负责执行工作，OpenClaw 负责盯住整个项目，而人类可以在任何时候通过 OpenClaw 或直接进入远端 session 介入。**

**状态：** 已完成第一次公开开源发布；Claude Code 路径已验证；更广泛的工具支持正在推进中。

## 核心能力

- 通过真实的远程 coding session 管理一个项目的开发进度
- 把 coding 工作推送到 Claude Code、Codex、OpenCode、Gemini CLI 这类 terminal-native coding agents 中执行
- 让 OpenClaw 持续跟进执行，并在工作偏航时纠正方向
- 由 OpenClaw 优先处理日常审批，只有必要时才升级给人类
- 在人类需要了解进展时，通过 OpenClaw 与 Telegram 等通道汇报状态
- 支持通过 OpenClaw 或直接进入远端 coding session 的方式接管
- 在 OpenClaw 或人类介入后，从实时终端状态继续推进

## CodeLeader 到底是做什么的

CodeLeader 面向的是这样一类场景：真正的执行环境本来就在远端——例如共享服务器、实验机、云端开发机、多设备协作，或者项目本身就已经放在远端机器上。

它不是把工作重新拉回本地 IDE，也不是把 coding AI 当成 ACP / Apex 这类协议优先的 swarm agents 来编排；CodeLeader 的做法是让执行继续留在真实的远端终端 session 里，由 OpenClaw 在上层持续管理整次运行。

一个典型流程是：

1. 你让 OpenClaw 去修复某台远程机器上的某个项目里的 bug，或实现其中一个功能。
2. OpenClaw 把工作推送到项目和算力本来就所在的远端 coding session。
3. OpenClaw 持续跟进这次执行，纠正偏航并处理日常审批。
4. 如果真的需要人类判断，OpenClaw 才会来问你。
5. 如果你愿意，你可以通过 OpenClaw 发起介入，或者直接进入远端 session 接手。
6. 之后工作会从当前真实状态继续推进。

## 为什么不是直接 SSH、后台 agent，或者桌面壳？

- **不只是 SSH：** SSH 只能给你终端连接，但不会自动提供你和 OpenClaw 之间共享的控制模型。
- **不只是后台 agent：** 后台自动化能跑，但你会失去可见性、结构化审批点，以及干净的 handoff 过程。
- **不只是桌面壳：** GUI 包装看起来更友好，但很多时候仍然把人绑在屏幕前。
- **CodeLeader 的切入点：** 让 coding tool 继续待在真实远端终端里，让 OpenClaw 负责控制层，让人类随时可以重新接管。

## 适合谁

如果你符合下面这些情况，CodeLeader 会比较适合你：

- 你已经在用，或准备把 OpenClaw 作为控制层
- 你的 coding tool 跑在远端机器、共享服务器、实验机或云端开发环境里
- 你希望能布置任务，但不想全程盯着终端
- 你仍然希望保留审批、可见性，以及在关键时刻由人类接管的能力
- 你偏好 terminal-native coding tools，而不是把 GUI 壳当成主产品

## 不太适合谁

如果你更偏向下面这些需求，那 CodeLeader 大概率不是最合适的选择：

- 你想要一个完全黑箱、没有人工检查点的全自动 coding agent
- 你想要的是本地桌面 IDE 替代品，而且这才是主产品形态
- 你的开发完全在本地完成，并不需要远端执行层
- 你更希望 first-class 的是点点点 GUI，而终端只是附属功能

## 为什么会有这个项目

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

开始使用只需要三件事：

1. **把 CodeLeader release bundle 安装到 OpenClaw skills 目录**
2. **确保本地机器可以 SSH 到将要运行 coding tool 的远端机器**
3. **直接告诉 OpenClaw 用 CodeLeader 处理一个真实任务**

例如：

```text
Use CodeLeader to build a Pomodoro timer app with task tracking.
```

OpenClaw 会在需要时自动补全缺失的启动信息，并通过这个 skill bundle 拉起整套系统。

如果你想亲自进入共享工作面：

```bash
ssh <remote-host>
codeleader show
```

这会直接打开远端的 CodeLeader session。

### Release bundle 目录名

解压后的 release 文件夹名称应保持为：

```text
codeleader/
```

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

## 联系方式

如果你想反馈问题、交流想法，或讨论合作，可以通过这个邮箱联系：

- `kunyan.cai@icloud.com`

## License

MIT
