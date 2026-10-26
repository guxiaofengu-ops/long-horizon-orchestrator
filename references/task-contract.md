# Task contract

JSON requires `schema_version: 1`, `name`, an existing absolute `workspace`, nonempty `phases`, positive `loop.max_iterations`, and positive budgets: `max_wall_seconds`, `max_phase_runs`, `max_failures`, `max_log_bytes`.

Each phase requires unique `name`, `command`, and nonempty `success`. Prefer an argv array. A string needs `shell: true`. Optional: `env`, `timeout_seconds`, `progress_jsonl`, `retry.max_attempts`, and `retry.backoff_seconds`. Set `checkpoint: true` when Codex must inspect validated results before the next phase/iteration; the resumed agent must review `report --json` and run `resume RUN_ID --approve-checkpoint`. Validators: `file` (`path`, `min_bytes`), `json` (`path`, `required_keys`), or `exit_code`. Zero exit is always required. File/JSON artifacts must be fresh for the attempt unless a validator explicitly sets `allow_stale: true`.

Progress is JSONL; each complete valid object counts as one step. Preflight passes after `preflight_steps` events or if the first phase validates sooner. Paths must remain inside the workspace.

Phases run in order per iteration. A successful iteration ends at `max_iterations` or when optional `loop.stop_file` exists.

Wake modes are `codex_queue` and `codex_exec` (both need a verified `thread_id`), `command` (argv with `{run_id}`, `{event}`, `{report}`, `{message}`), and `none`. See `examples/demo_contract.json`. Never guess a thread ID.
