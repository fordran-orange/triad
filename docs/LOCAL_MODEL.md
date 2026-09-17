# Local model support

Ollama is optional. `tools/health_check.py` probes its loopback `/api/tags` endpoint
and records installed model names if reachable. `.env.example` supports
`OLLAMA_URL`, `OLLAMA_MODEL=qwen3:4b` and `LOCAL_MODEL_ENABLED=false`.
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

The CLI version, `/api/version` and `/api/tags` were verified. `qwen3:4b` is installed
and selected in the environment, settings default and example policy. Triad's helper runtime remains disabled;
installing the server does not grant it tools or decision authority.

Start the application using the Windows Start menu or
`C:\Users\fordr\AppData\Local\Programs\Ollama\ollama app.exe`.
New terminals use the installer-added PATH entry for `ollama --version` and `ollama list`.
Logs live under `%LOCALAPPDATA%\Ollama`. Model files are shared local infrastructure,
not part of Git. See [Ollama Windows documentation](https://docs.ollama.com/windows).

## Selected helper model

The operator selected `qwen3:4b` (Ollama ID `359d7dd4bcda`, approximately 2.5 GB).
The download's SHA-256 verification completed successfully, and its manifest is in
`C:\AI\Models\Ollama\manifests\registry.ollama.ai\library\qwen3\4b`.
`tools/health_check.py` confirms that the configured model is installed.

Run `.venv\Scripts\python.exe tools/check_local_model.py` for a synthetic summary
probe. This uses a 2,048-token context, a 512-token generation ceiling and a 120-second
HTTP timeout, then unloads the model. This is a direct operator diagnostic, not an
agent invocation or a policy budget increase. Its result goes to
`logs/local-model.latest.json`. A completed response is not a quality benchmark.

Initial 96/192-token probes truncated before a final summary; the installed model
continued producing reasoning despite non-thinking flags. The diagnostic therefore
allows thinking explicitly and rejects token-limit truncation. Helper latency and
instruction adherence need evaluation before enabling an automated worker.

Verified smoke result on 2026-09-17: a complete summary returned in 34.29 seconds
(248 generated tokens including reasoning), correctly preserving 120 processed
records, 2 rejected records and missing timestamps as the rejection cause.
