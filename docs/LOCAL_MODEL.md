# Local model support

Ollama is optional. `tools/health_check.py` probes its loopback `/api/tags` endpoint
and records installed model names if reachable. `.env.example` supports
`OLLAMA_URL`, `OLLAMA_MODEL=qwen3:8b` and `LOCAL_MODEL_ENABLED=false`.
No model is downloaded automatically and no inference runtime is wired on Day 1.
Inspect `ollama list`, start `ollama serve` if needed,
then choose a Qwen model that fits available memory. Enabling the config flag alone
does not start a worker.

The local Qwen model is a helper, not an autonomous fourth Triad decision-maker.
Allowed tasks: summarization, log analysis, document classification, tagging,
retrieval preparation, context compression and housekeeping within approved scratch
space. Human review is required before helper output becomes authoritative evidence.

It cannot increase risk, change execution authority/system policy, approve live
trades, or raise compute/permission limits. The policy example caps it at 4,096
tokens and 60 seconds; compiler ceilings are 8,192 tokens and 120 seconds.
Do not share `.env`, admin credentials, policy-write access or arbitrary shell tools.
Runtime adapters enforcing these limits remain future work.

## Verified Windows installation — 2026-09-17

Ollama 0.34.1 is installed at `C:\Users\fordr\AppData\Local\Programs\Ollama`.
The official installer has a valid Authenticode signature from Ollama Inc.
Model storage is `C:\AI\Models\Ollama`, outside this repository, configured through
the persistent user environment variable `OLLAMA_MODELS`.
`OLLAMA_HOST=127.0.0.1:11434` keeps the API local to this machine.

The CLI version, `/api/version` and `/api/tags` were verified. No models are installed
yet, so Qwen inference is not available. Triad's helper runtime remains disabled;
installing the server does not grant it tools or decision authority.

Start the application using the Windows Start menu or
`C:\Users\fordr\AppData\Local\Programs\Ollama\ollama app.exe`.
New terminals use the installer-added PATH entry for `ollama --version` and `ollama list`.
Logs live under `%LOCALAPPDATA%\Ollama`. Model files are shared local infrastructure,
not part of Git. See [Ollama Windows documentation](https://docs.ollama.com/windows).
