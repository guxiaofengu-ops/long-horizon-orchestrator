# Codex 支持边界（已于 2026-10-26 验证）

构建主机使用 Codex CLI 0.154.0，提供 `codex queue`、`codex exec resume`，以及基于 stdio、Unix Socket 和 WebSocket 的 App Server。OpenAI 官方文档介绍了 `thread/resume` + `turn/start`，并说明宿主应用负责其界面。

共享的受管理 thread 应优先使用 `codex_queue`。`codex_exec` 可以恢复上下文，但输出流位于其新进程中。官方文档没有说明已打开的普通 TUI 会实时重绘。本 Skill 不使用 PTY 抓取或键盘注入。

- https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server
- https://developers.openai.com/blog/codex-as-a-platform

CLI 支持会发生变化，因此请在部署主机上运行 `scripts/lho doctor`。

2026-10-28 在 Linux CLI 0.155.1 的实际会话中，任务失败时原回合仍在执行，`codex queue` 入队的失败通知到原回合结束后才被消费。项目因此将新队列投递记为 `queued`，不再用 `sent` 暗示模型回合已经执行。CLI 0.164.0 主机上发现另一任务配置为 `none`，失败时只生成 `manual_required`；这与队列消费延迟是两个不同问题。自动任务应显式使用 `--require-wakeup`，并为无人值守运行核实宿主是否持续消费队列。
