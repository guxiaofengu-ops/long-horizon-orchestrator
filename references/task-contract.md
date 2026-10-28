# 任务契约

JSON 必须包含 `schema_version: 1`、`name`、指向已有目录的绝对路径 `workspace`、非空 `phases`、正整数 `loop.max_iterations`，以及正整数预算：`max_wall_seconds`、`max_phase_runs`、`max_failures`、`max_log_bytes`。

每个阶段都需要唯一的 `name`、`command` 和非空 `success`。优先使用 argv 数组；字符串命令需要设置 `shell: true`。可选字段包括 `env`、`timeout_seconds`、`progress_jsonl`、`retry.max_attempts` 和 `retry.backoff_seconds`。当 Codex 必须在下一阶段或下一轮之前检查已验证的结果时，设置 `checkpoint: true`；恢复后的 Agent 必须检查 `report --json`，再运行 `resume RUN_ID --approve-checkpoint`。验证器包括 `file`（`path`、`min_bytes`）、`json`（`path`、`required_keys`）或 `exit_code`。退出码始终必须为零。文件和 JSON 产物必须在当前尝试中生成，除非验证器显式设置 `allow_stale: true`。

进度使用 JSONL；每个完整且合法的对象计为一个 step。收到 `preflight_steps` 个事件后预检通过；如果第一阶段更早通过验证，也视为通过。路径必须位于 workspace 内。

每一轮都按顺序运行各阶段。成功的迭代在达到 `max_iterations`，或可选的 `loop.stop_file` 存在时结束。

唤醒模式包括 `codex_queue` 和 `codex_exec`（两者都需要经过验证的 `thread_id`）、`command`（argv 可包含 `{run_id}`、`{event}`、`{report}`、`{message}`）以及 `none`。参见 `examples/demo_contract.json`。绝不猜测 thread ID。

自动恢复需求使用 `start CONTRACT --require-wakeup`，避免默认的 `none` 被误认为已配置通知。队列模式的完成状态为 `queued`，表示入队成功；模型回合是否实际完成需要另外的宿主证据。原回合活跃时，排队等待不等于通知丢失。
