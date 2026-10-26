# 运维说明

运行器不需要第三方 Python 依赖。

```bash
scripts/lho doctor
scripts/lho validate contract.json
scripts/lho start contract.json --wait-preflight
scripts/lho status RUN_ID
scripts/lho attach RUN_ID
scripts/lho report RUN_ID --json
```

状态默认保存在 `~/.local/state/long-horizon-orchestrator`，可通过 `LHO_STATE_DIR` 或 `--state-dir` 修改。

支持的后端：

- `local`：独立本地进程组。
- `tmux`：独立 tmux session。
- `slurm`：通过 `sbatch` 提交。
- `systemd`：通过用户级 `systemd-run` 运行。

Worker 会原子写入每次尝试的结果。替代 Supervisor 可以从结果恢复；SQLite 租约会阻止重复推进。

控制语义：

- `pause`：允许当前外部命令结束，但不再启动下一阶段。
- `resume`：清除暂停并恢复 Supervisor。
- `resume --approve-checkpoint`：确认 AI 已审查结果，然后推进检查点。
- `cancel`：标记取消，并终止精确记录的进程组。
- `logs` 和 `attach`：只查看本地状态，不调用模型。

如果唤醒状态为 `dispatch_unknown`，应先检查目标线程。仅在确认消息没有送达后，才执行 `resume --retry-wakeup`，避免产生重复 Agent 回合。
