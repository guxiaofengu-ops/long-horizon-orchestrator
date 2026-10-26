# 任务契约

契约使用 JSON。必填字段包括：`schema_version: 1`、`name`、已存在的绝对路径 `workspace`、非空 `phases`、正整数 `loop.max_iterations`，以及正整数预算 `max_wall_seconds`、`max_phase_runs`、`max_failures`、`max_log_bytes`。

每个阶段必须包含唯一 `name`、`command` 和非空 `success`。推荐使用 argv 数组；字符串命令必须显式设置 `shell: true`。可选字段包括 `env`、`timeout_seconds`、`progress_jsonl`、`retry.max_attempts` 和 `retry.backoff_seconds`。

当 Codex 必须在下一阶段或下一轮之前检查结果时，设置 `checkpoint: true`。恢复后的 Agent 应先运行 `report RUN_ID --json`，确认结果后再执行：

```bash
scripts/lho resume RUN_ID --approve-checkpoint
```

验证器类型：

- `file`：支持 `path`、`min_bytes`。
- `json`：支持 `path`、`required_keys`。
- `exit_code`：支持 `equals`。

进程退出码始终必须为零。文件和 JSON 产物默认必须比当前尝试更新；仅当契约明确设置 `allow_stale: true` 时才允许旧产物。

进度文件使用 JSONL，每个完整且合法的 JSON 对象算作一个 step。达到 `preflight_steps` 或第一阶段提前验证成功时，启动预检通过。所有路径必须位于工作区内。

唤醒模式包括：

- `codex_queue`：需要经过验证的 `thread_id`。
- `codex_exec`：需要经过验证的 `thread_id`。
- `command`：显式 argv，可使用 `{run_id}`、`{event}`、`{report}`、`{message}` 占位符。
- `none`：记录需要人工恢复。

完整结构参见 [`examples/demo_contract.json`](../../examples/demo_contract.json)。不要猜测线程 ID。
