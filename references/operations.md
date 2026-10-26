# Operations

No third-party Python dependency is required.

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

If wakeup is `dispatch_unknown`, inspect the thread and use `resume --retry-wakeup` only after confirming non-delivery. Install by copying this folder to `~/.codex/skills/long-horizon-orchestrator`.
