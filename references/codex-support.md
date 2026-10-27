# Codex 支持边界（已于 2026-10-26 验证）

构建主机使用 Codex CLI 0.154.0，提供 `codex queue`、`codex exec resume`，以及基于 stdio、Unix Socket 和 WebSocket 的 App Server。OpenAI 官方文档介绍了 `thread/resume` + `turn/start`，并说明宿主应用负责其界面。

共享的受管理 thread 应优先使用 `codex_queue`。`codex_exec` 可以恢复上下文，但输出流位于其新进程中。官方文档没有说明已打开的普通 TUI 会实时重绘。本 Skill 不使用 PTY 抓取或键盘注入。

- https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server
- https://developers.openai.com/blog/codex-as-a-platform

CLI 支持会发生变化，因此请在部署主机上运行 `scripts/lho doctor`。
