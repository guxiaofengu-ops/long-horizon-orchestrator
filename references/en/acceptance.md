# Real CLI acceptance ladder

The opt-in `scripts/acceptance.py` harness exercises the **installed** skill through real Codex CLI turns. It does not replace real elapsed time with a simulated clock.

The default progression is 10 seconds → 60 seconds → 300 seconds → 18,010 seconds (5 hours 10 seconds). Each stage runs synthetic numerical inference, resumes the same verified Codex session for review, runs a five-second training fixture, then resumes Codex to inspect results and write a verification receipt. These are acceptance fixtures, not production ML benchmarks.

Use an explicitly created acceptance session ID, with its initial `thread.started` event saved as evidence:

```sh
python3 scripts/acceptance.py ladder --execute \
  --output /absolute/path/to/acceptance-evidence \
  --thread-id VERIFIED_TEST_SESSION_ID
```

This makes real model calls at phase boundaries. The local monitor loop makes no model calls. It records progress every 30 seconds and can restart an expired run supervisor. On macOS, a bounded `caffeinate -i -w DRIVER_PID` can keep an active test from idle sleep without changing power settings. Closing the lid, shutdown, logout, or loss of power still affects a local test.

Evidence includes `ladder.json`, `monitor.jsonl`, per-stage contracts and artifacts, Codex JSONL streams, SQLite attempts and wakeup ledger, and a Codex-written verification receipt. A stage is marked passed only after its minimum duration, both artifact validators, a successful resumed turn, and the verification receipt are observed.

Do not describe a running five-hour stage as passed. Preserve the remote-install ref and file hashes, baseline failures, fixes, and final elapsed time separately.
