<div align="center">

**English** | [简体中文](README.md)

<img src="docs/assets/mark.svg" width="92" alt="Long Horizon Orchestrator mark">

# Long Horizon Orchestrator

**Let Codex make decisions—not spend tokens watching jobs run.**

A durable Codex Skill for inference → review → training loops with SQLite state, detached workers, bounded preflight checks, and official session wakeups.

[![Tests](https://github.com/guxiaofengu-ops/long-horizon-orchestrator/actions/workflows/test.yml/badge.svg)](https://github.com/guxiaofengu-ops/long-horizon-orchestrator/actions/workflows/test.yml)
[![Skill validation](https://img.shields.io/badge/Codex%20Skill-valid-16a34a)](SKILL.md)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776ab)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-f59e0b.svg)](LICENSE)

[Live documentation](https://guxiaofengu-ops.github.io/long-horizon-orchestrator/) · [Quick start](#quick-start) · [Task contract](references/en/task-contract.md) · [Operations](references/en/operations.md)

</div>

## Why this exists

Long inference and training jobs should not keep an agent turn—and its model context—alive for hours. Long Horizon Orchestrator separates judgment from waiting:

```text
Codex edits pipeline
        │
        ▼
bounded preflight ── healthy ──▶ Codex turn ends
        │                              │
        ▼                              ▼
detached worker ◀── SQLite state ── watchdog
        │
        ├── validated checkpoint ──▶ official Codex wakeup ──▶ review
        ├── serious failure ───────▶ official Codex wakeup ──▶ diagnose
        └── terminal success ──────▶ official Codex wakeup ──▶ report
```

During the long wait, the runner makes **zero model calls**.

## Highlights

- Durable SQLite state machine with lease-based duplicate protection
- Independent phase workers that survive runner disconnection
- Inference/training loops with explicit AI review checkpoints
- Local, tmux, SLURM, and systemd scheduler backends
- Artifact freshness, JSON, file-size, and exit-code validation
- Wall-time, phase-run, failure, and log-size budgets
- Idempotent event ingestion and conservative at-most-once wakeups
- Official `codex queue` integration, with `codex exec resume` fallback
- Honest terminal boundary: no keyboard injection or PTY scraping

## Quick start

### Install as a Codex Skill

```bash
git clone https://github.com/guxiaofengu-ops/long-horizon-orchestrator.git \
  ~/.codex/skills/long-horizon-orchestrator
```

Start a new Codex turn and ask:

```text
Use $long-horizon-orchestrator to run this inference/training pipeline
with a review checkpoint between phases.
```

### Run the CLI directly

```bash
scripts/lho doctor
cp examples/demo_contract.json ./my-run.json
# Edit workspace, commands, validators, budgets, and wakeup settings.
scripts/lho validate ./my-run.json
scripts/lho start ./my-run.json --wait-preflight
```

Operator commands:

```bash
scripts/lho status RUN_ID
scripts/lho logs RUN_ID --follow
scripts/lho attach RUN_ID
scripts/lho pause RUN_ID
scripts/lho resume RUN_ID
scripts/lho resume RUN_ID --approve-checkpoint
scripts/lho cancel RUN_ID
scripts/lho report RUN_ID --json
```

## Checkpoints, not polling

Add `"checkpoint": true` to any phase that requires agent judgment. Once the external command exits successfully and every artifact validator passes, the runner persists `WAITING_FOR_CODEX`, sends one wakeup, and stops. The resumed agent reviews the report before explicitly advancing.

```json
{
  "name": "inference",
  "command": ["python", "infer.py"],
  "progress_jsonl": ".lho/inference.jsonl",
  "checkpoint": true,
  "success": [
    {"type": "json", "path": "outputs/metrics.json", "required_keys": ["accuracy"]}
  ]
}
```

## Supported wakeup paths

| Mode | Best for | Behavior |
|---|---|---|
| `codex_queue` | Managed Codex App/App Server thread | Queues a visible message in the verified thread |
| `codex_exec` | Persisted CLI session | Resumes context in a new noninteractive process |
| `command` | Approved integration or tests | Executes an explicit argv template |
| `none` | Manual operation | Records that an operator must resume |

An already-open ordinary TUI is not guaranteed to repaint when another process resumes its session. This project does not pretend otherwise; see [the verified support boundary](references/en/codex-support.md).

## Verification

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile scripts/lho_core.py scripts/lho_worker.py
```

The acceptance suite covers early preflight, inference → training loops, checkpoints, failure handling, pause/resume, duplicate supervisors/events, and runner-loss recovery. See [TEST_RESULTS.md](TEST_RESULTS.md).

## Security model

Commands run with the invoking user's permissions. Prefer argv arrays, keep validators inside the workspace, set finite budgets, and never place credentials in contracts or progress logs. Read [SECURITY.md](SECURITY.md) before production use.

## Project status

The core runner is usable and tested on macOS with Python 3.13. Scheduler adapters for SLURM and systemd are implemented but require their native commands on the deployment host. Real session delivery depends on the Codex host and verified thread ID.

## Contributing

Issues and focused pull requests are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) and follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## License

MIT © 2026 Gu Xiaofeng. See [LICENSE](LICENSE).

## Windows

Use `python scripts/lho ...` with the `local` backend. Native Job Objects own each command tree, including descendants, for cancellation, phase timeouts, budget enforcement and worker-loss cleanup. Background processes hide their console windows. The CI matrix includes Windows, Linux and macOS. See [Windows operations](references/windows.md).
