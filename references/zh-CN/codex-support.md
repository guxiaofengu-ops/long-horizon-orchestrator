# Codex 支持边界

本项目在 2026-10-26 使用 Codex CLI 0.154.0 验证。该版本提供 `codex queue`、`codex exec resume`，以及基于 stdio、Unix Socket 和 WebSocket 的 App Server。生成的 App Server schema 包含 `thread/resume` 和 `turn/start`。

因此：

1. 对共享的受管理线程，优先使用 `codex_queue`。
2. `codex_exec` 可以恢复上下文，但输出属于新启动的进程。
3. 官方没有保证一个已经打开的普通 TUI 会因外部进程恢复会话而实时重绘。
4. 本项目不会使用 PTY 抓取、键盘注入或模拟输入。

官方资料：

- https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server
- https://developers.openai.com/blog/codex-as-a-platform

不同主机上的 CLI 支持可能变化，请运行 `scripts/lho doctor` 检查实际环境。
