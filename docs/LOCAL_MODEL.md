# Local model support

Ollama is optional. `tools/health_check.py` probes its loopback `/api/tags` endpoint
and records installed model names if reachable. `.env.example` supports
`OLLAMA_URL`, `OLLAMA_MODEL=qwen3:8b` and `LOCAL_MODEL_ENABLED=false`.
No model is downloaded automatically and no inference runtime is wired on Day 1.
If Ollama is later installed, inspect `ollama list`, start `ollama serve` if needed,
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
