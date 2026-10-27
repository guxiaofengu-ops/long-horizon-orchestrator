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

Windows 使用 `python scripts/lho ...`，原生进程树管理和恢复边界详见 [Windows 运行说明](windows.md)。
