---
name: long-horizon-orchestrator
description: Run durable inference/training or other long pipelines outside the model loop, with persisted state, bounded early checks, and an official Codex session wakeup only when results or serious failures need judgment. Use for long background jobs or repeated phases, not short commands that should finish in the current turn.
---

# Long Horizon Orchestrator

把机械等待移出 Codex 回合，把判断留给 Codex。

1. 检查 pipeline、成功产物、进度信号、安全停止行为和成本上限。绝不虚构成功证据。
2. 阅读 [task-contract.md](references/task-contract.md) 并创建 JSON 契约。优先使用 argv 数组；仅在确有需要时启用 shell。
3. 从可信宿主上下文获取当前 Codex thread ID。绝不猜测；无法获取时使用 `wakeup.mode: "none"`。
4. 运行 `python3 scripts/lho start CONTRACT --wait-preflight`（从归档安装且没有可执行位时，Python 前缀同样有效）。检查早期步骤和启动日志。确认健康后结束 Codex 回合；绝不使用模型调用轮询长任务。
5. 独立 Runner 负责等待、阶段转换、重试、验证、预算和唤醒。恢复后运行 `scripts/lho report RUN_ID --json`，核验证据；仅在尚未满足终止条件时启动下一次有界运行。

使用 `status`、`logs`、`attach`、`pause`、`resume`、`cancel` 和 `report`。阅读 [operations.md](references/operations.md)。无人值守恢复需要持久 Supervisor 服务或独立 Watchdog；仅有独立本地进程并不等于操作系统重启服务。

Windows 使用 `python scripts/lho ...` 和 `local` 后端；后台进程隐藏控制台，命令及其后代通过原生 Job Object 管理。部署前验证取消、阶段超时、墙钟预算和 Worker 意外退出，具体操作见 [Windows 运行说明](references/windows.md)。设备占用检查及远端清理由任务自身的执行器负责。

## 边界

- 等待过程不发起模型调用。只有已配置的官方唤醒适配器可以排入或启动 Codex 回合。
- 对受管理的 App Server thread，优先使用 `codex queue --thread ... --message ...`。`codex exec resume` 是回退方案，其输出属于新进程。
- 不注入按键、不抓取终端，也不承诺已打开的原生 TUI 会刷新。阅读 [codex-support.md](references/codex-support.md)。
- 将验证器限制在 workspace 内，遵守授权边界，绝不在契约、日志或 prompt 中放置秘密信息。
- `pause` 会等待当前命令结束并停止调度；`cancel` 会终止精确记录的进程组或 Windows Job Object，不按进程名批量结束任务。
- 墙钟时间、迭代次数、失败次数、阶段运行次数和日志大小都必须有有限预算。仅重试明确标记为可重试的工作。
- 成功要求退出码为零且通过所有已声明验证器。仅有 submitted、running 或 exited 状态不代表成功。
- 唤醒采用保守的至多一次语义。投递不明确时应显式暴露，而不是盲目重试。

交接时必须说明 run ID、路径、后端、预检证据、预算、唤醒模式、恢复命令，以及是否实际执行过真实 Codex 唤醒。
