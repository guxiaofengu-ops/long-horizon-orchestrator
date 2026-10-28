# Linux 长程运行与唤醒排查

先在运行所在主机、同一用户和相同 state 目录执行：

```sh
python3 scripts/lho --state-dir /absolute/path/to/state status RUN_ID
python3 scripts/lho --state-dir /absolute/path/to/state report RUN_ID --json
```

检查 `runs/RUN_ID/supervisor.log`、`run.log`、`worker-launch.log`、`attempts/*.result.json` 和 `codex-*.jsonl`。`run.log` 是外部命令日志；Supervisor 崩溃和唤醒适配器错误不一定出现在其中。报告中的 `wakeups[].detail` 保存投递错误，`status` 输出的 `lease_owner`、`lease_until`、`updated` 可用于判断 Supervisor 最近是否仍在续租。

## 根据证据恢复

- `RUNNING` 且租约持续有效：检查命令进度、阶段 `timeout_seconds` 和总预算。下载还在执行时，经过一夜并不自动形成检查点。`preflight_passed=0` 只表示尚未达到预检所需的 JSONL 进度或首阶段验证条件。
- `RUNNING` 或 `STARTING` 且租约已过期：运行 `resume RUN_ID` 启动替代 Supervisor，复用已记录的 Worker/结果，保留原预算。它不会把已取消、失败或预算耗尽的运行变成新任务。
- `WAITING_FOR_CODEX` 且唤醒为 `pending`：运行 `supervise RUN_ID` 恢复尚未发送的检查点通知。恢复过程不重跑阶段；审查后仍需 `resume RUN_ID --approve-checkpoint` 才会推进。
- 检查点或终态的 `dispatching` 超过投递时限：再次运行 `supervise RUN_ID` 会将其显式标记为 `dispatch_unknown`。阈值为适配器超时加 60 秒宽限；`codex_exec` 使用配置的 `wakeup.timeout_seconds`（默认 300），其他适配器使用 60 秒。
- `dispatch_unknown`：检查目标 thread 和投递证据，只有确认没有送达后才运行 `resume RUN_ID --retry-wakeup`。重试记录保存在事件中；不会自动重发投递不明的通知。
- `sent`：含义取决于适配器。`codex_queue` 表示命令成功入队；`codex_exec` 还要求观察到 `turn.completed`。后者的输出属于独立 CLI 进程，不能据此断言已打开的 TUI 已刷新。

示例中的子命令均可接在 `python3 scripts/lho --state-dir /absolute/path/to/state` 后。实际 run ID、state 目录和 thread ID 应来自目标主机证据。

## 无人值守边界

`local` 进程脱离启动终端后仍可继续工作，但没有内置的常驻 Watchdog 或开机自启机制。Supervisor 被系统、会话清理或 OOM 终止后，不会自行重新出现。无人值守部署应配置独立服务或 Watchdog，在租约过期时运行 `supervise RUN_ID`；它也应检查待发送检查点和终态通知。只检查 `RUNNING` 会遗漏通知恢复场景。等待循环不得调用模型，正常运行中的重复 Supervisor 由 SQLite 租约和唤醒事件唯一键拦截。

更新脚本不会替换已在内存中运行的 Supervisor。升级前先保存状态和日志，并按目标主机的服务管理方式重启对应 Supervisor；保留 state 数据库、契约、attempts 和 Worker，不要另起重复下载任务。旧 Linux attempt 缺少 `cancel_path` 时仍支持按已记录进程组取消。
