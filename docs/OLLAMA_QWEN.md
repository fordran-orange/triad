# Ollama / local Qwen

LOCAL_QWEN uses the fixed local endpoint `http://127.0.0.1:11434`, model `qwen3:4b`
by default, and LOCAL billing. The provider screen can inspect installed models,
change the selected model, refresh, test and enable/disable the helper.

Qwen WorkItem verification uses `day3.support.support`, SUMMARY capability, a
bounded operator-supplied journal, a persisted Control Plane decision, schema
validation, journals/handoff and transport/usage provenance. It does not give a
frontier agent unrestricted control of Ollama. Helper results remain reviewable.

This machine stores models at `C:\AI\Models\Ollama`, set by the user's
`OLLAMA_MODELS` environment variable. A long-lived parent process may not inherit
new user environment settings. Starting serve with an empty/default model path
can report no models even though the 4B model files are present.
Day 5A restored the configured model directory without downloading another model.

See DAY5A_VERIFICATION.md for actual inference results and any current blockers.
Tag listing and server reachability alone never produce ONLINE.
