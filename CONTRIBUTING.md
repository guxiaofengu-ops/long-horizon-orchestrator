# Contributing

Thanks for helping improve Long Horizon Orchestrator.

## Before opening a change

1. Open an issue for behavioral changes or new integrations.
2. Keep waiting paths model-free and preserve existing authorization boundaries.
3. Do not add implicit shell execution, unbounded retries, or terminal-input simulation.
4. Add an observable test for state-machine changes.

## Local checks

```bash
python3 -m py_compile scripts/lho_core.py scripts/lho_worker.py
python3 -m unittest discover -s tests -v
```

Pull requests should explain the failure mode being addressed, the state transition affected, and the evidence used for success. Never include credentials, production run databases, or customer artifacts.
