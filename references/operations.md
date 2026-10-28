# 运维说明

不需要第三方 Python 依赖。

从归档或下载文件安装时，可执行位可能缺失：请使用 `python3 scripts/lho ...` 调用每条命令。内部 Supervisor 使用当前 Python 解释器，不依赖文件的可执行模式。

```sh
scripts/lho doctor
scripts/lho validate contract.json
scripts/lho start contract.json --wait-preflight
scripts/lho status RUN_ID
scripts/lho attach RUN_ID
scripts/lho report RUN_ID --json
```

状态默认保存在 `~/.local/state/long-horizon-orchestrator`；可通过 `LHO_STATE_DIR` 或 `--state-dir` 覆盖。支持的后端为独立 `local`、`tmux`、`slurm` 和 `systemd`。

Worker 会原子持久化结果。替代 Supervisor 可以恢复结果；可续期的 SQLite 租约会阻止重复推进。`pause` 等待当前命令完成后停止；`cancel` 只针对已记录的 POSIX 进程组或 Windows Job Object。`logs` 和 `attach` 永远不会调用模型。

`codex_exec` 会等待实际的 `turn.completed` 通知，之后才把唤醒标记为已发送。流式证据保存在 `codex-<event>.jsonl`。可选的 `wakeup.config` 接受 Codex 配置覆盖字符串，`wakeup.timeout_seconds` 限制恢复回合的时长（默认 300）。失败或未确认的回合会变成 `dispatch_unknown`，绝不会被静默报告为成功。

如果唤醒状态为 `dispatch_unknown`，请检查目标 thread，并且仅在确认未投递后使用 `resume --retry-wakeup`。安装时将此目录复制到 `~/.codex/skills/long-horizon-orchestrator`。

自动恢复任务使用 `start CONTRACT --require-wakeup --wait-preflight`。该选项会在启动前拒绝 `wakeup.mode: "none"`；兼容的手动启动方式仍可使用 `none`，但会在 stderr 明确警告不会自动通知。`codex_queue` 成功时记录为 `queued`，只有队列接收得到确认；原回合繁忙或宿主未消费队列时，不代表模型已开始执行。`codex_exec` 的 `sent` 则要求完整回合证据。

为尚未结束的运行修正未来通知配置，可使用：

```sh
python3 scripts/lho configure-wakeup RUN_ID --mode codex_queue --thread-id VERIFIED_THREAD_ID --codex-bin /absolute/path/to/codex
```

这会同步持久契约和配置事件，不重启 Worker、不重置预算、不发送测试消息，也不改写既有投递记录。thread ID 必须事先通过可信宿主上下文或该会话的 `session_meta` 核实；终态运行不能用此命令重新配置。已加载旧脚本的 Supervisor 需要单独重启才能使用新的状态报告语义。

Windows 使用 `python scripts/lho ...`，原生进程树管理和恢复边界详见 [Windows 运行说明](windows.md)。

Linux 上长时间没有触发时，应同时检查 Supervisor 租约、检查点/终态唤醒记录和实际命令进度。具体恢复步骤与无人值守边界见 [Linux 唤醒排查](linux-recovery.md)。
