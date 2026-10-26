---
name: long-horizon-orchestrator
description: Run durable inference/training or other long pipelines outside the model loop, with persisted state, bounded early checks, and an official Codex session wakeup only when results or serious failures need judgment. Use for long background jobs or repeated phases, not short commands that should finish in the current turn.
---

# Long Horizon Orchestrator

Move mechanical waiting out of the Codex turn. Keep judgment in Codex.

1. Inspect the pipeline, success artifacts, progress signal, safe stop behavior, and cost limits. Never invent success evidence.
2. Read [task-contract.md](references/task-contract.md) and create a JSON contract. Prefer argv arrays; opt into shell only when required.
3. Obtain the current Codex thread ID from trusted host context. Never guess it. If unavailable, use `wakeup.mode: "none"`.
4. Run `scripts/lho start CONTRACT --wait-preflight`. Inspect early steps and the launch log. If healthy, end the Codex turn; never poll long work with model calls.
5. The detached runner owns waiting, phase transitions, retries, validation, budgets, and wakeup. On resume, run `scripts/lho report RUN_ID --json`, verify evidence, and start another bounded run only if termination has not been met.

Use `status`, `logs`, `attach`, `pause`, `resume`, `cancel`, and `report`. Read [operations.md](references/operations.md).

## Boundaries

- Waiting makes no model calls. Only the configured official wakeup adapter may queue/start a Codex turn.
- Prefer `codex queue --thread ... --message ...` for a managed App Server thread. `codex exec resume` is a fallback whose output belongs to its new process.
- Never inject keys, scrape a terminal, or promise an already-open native TUI will repaint. Read [codex-support.md](references/codex-support.md).
- Keep validators inside the workspace, preserve authorization boundaries, and never put secrets in contracts/logs/prompts.
- Pause finishes the active command and stops scheduling. Cancel terminates the exact recorded process group.
- Require finite wall-time, iteration, failure, phase-run, and log-size budgets. Retry only explicitly retryable work.
- Success requires zero exit plus every declared validator. Submitted/running/exited alone is not success.
- Wakeup is conservative at-most-once. Ambiguous dispatch is surfaced, not blindly retried.

Handoff must state run ID, paths, backend, preflight evidence, budgets, wakeup mode, recovery command, and whether a real Codex wakeup was exercised.
