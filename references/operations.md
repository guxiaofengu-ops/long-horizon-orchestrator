# Operations

No third-party Python dependency is required.

For archive/download installations, executable bits may be absent: invoke every command with `python3 scripts/lho ...`. Internal supervisors use the current Python interpreter and do not depend on executable file modes.

```sh
scripts/lho doctor
scripts/lho validate contract.json
scripts/lho start contract.json --wait-preflight
scripts/lho status RUN_ID
scripts/lho attach RUN_ID
scripts/lho report RUN_ID --json
```

State defaults to `~/.local/state/long-horizon-orchestrator`; override with `LHO_STATE_DIR` or `--state-dir`. Backends: detached `local`, `tmux`, `slurm`, and `systemd`.

Workers atomically persist results. A replacement supervisor recovers them; a renewable SQLite lease prevents duplicate advancement. Pause finishes the active command then stops. Cancel targets only the recorded process group. Logs/attach never invoke a model.

`codex_exec` waits for an actual `turn.completed` notification before marking a wakeup sent. Stream evidence is stored in `codex-<event>.jsonl`. Optional `wakeup.config` accepts Codex config override strings, and `wakeup.timeout_seconds` bounds a resumed turn (default 300). A failed or unconfirmed turn becomes `dispatch_unknown`; it is never silently reported as successful.

If wakeup is `dispatch_unknown`, inspect the thread and use `resume --retry-wakeup` only after confirming non-delivery. Install by copying this folder to `~/.codex/skills/long-horizon-orchestrator`.
