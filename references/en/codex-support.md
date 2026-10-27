# Codex support boundary (verified 2026-10-26)

The build host had Codex CLI 0.154.0, exposing `codex queue`, `codex exec resume`, and App Server over stdio/Unix/WebSocket. Official OpenAI documentation describes `thread/resume` + `turn/start` and says the host application owns its interface.

`codex_queue` is preferred for a shared managed thread. `codex_exec` resumes context but streams in its new process. An already-open ordinary TUI is not documented to repaint live. This skill avoids PTY scraping and keyboard injection.

- https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server
- https://developers.openai.com/blog/codex-as-a-platform

Run `scripts/lho doctor` on the deployment host because CLI support changes.
