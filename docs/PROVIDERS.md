# Providers

## Day 5A supersedes the API-only setup below

Open [Settings → AI Providers](http://127.0.0.1:8000/settings/ai-providers).
CODEX, CLAUDE and GROK are logical agents with subscription CLI transports preferred
and APIs optional. LOCAL_QWEN remains an Ollama helper. Production API credentials
now use Windows Credential Manager; model/pricing/fallback settings use the UI.
No normal provider setup requires editing `.env`. Fallback defaults to NEVER.
Explicit operator UI authorization can set the global API daily ceiling up to $25;
agents cannot raise it. CLI WorkItems remain blocked pending outer isolation.
See [provider control](AI_PROVIDER_CONTROL.md), [transports](AGENT_TRANSPORTS.md)
and [current verification](DAY5A_VERIFICATION.md).

## Historical Day 3 adapter contract (retained for legacy scripts/tests)

`app/triad/day3/adapters.py` owns transport, provider prompt compilation, health, capabilities, metadata and cost estimates. Orchestration consumes the AgentProvider interface. CODEX is the logical OpenAI API role; a Codex desktop subscription is not an API credential.

| Agent | Provider / endpoint | Required configuration |
|---|---|---|
| CODEX | OpenAI `/v1/responses` | OPENAI_API_KEY, OPENAI_MODEL, OPENAI_INPUT_USD_PER_MILLION, OPENAI_OUTPUT_USD_PER_MILLION |
| CLAUDE | Anthropic `/v1/messages` | ANTHROPIC_API_KEY, ANTHROPIC_MODEL, ANTHROPIC_INPUT_USD_PER_MILLION, ANTHROPIC_OUTPUT_USD_PER_MILLION |
| GROK | xAI `/v1/chat/completions` | XAI_API_KEY, XAI_MODEL, XAI_INPUT_USD_PER_MILLION, XAI_OUTPUT_USD_PER_MILLION |
| LOCAL_QWEN | Ollama `/api/generate` | OLLAMA_MODEL=qwen3:4b; configured local Ollama URL |

Environment variables or ignored local `.env` supply configuration. `.env.example` contains blank cloud keys/models/rates. Select account-supported models and verified pricing before authorizing cloud spend. The persisted daily cloud ceiling starts at $0. UI controls only lower it; authorizing a higher ceiling requires a separately reviewed human governance change, never agent self-approval.

Health confirms the configured model through provider model listings. Missing keys/models are UNAVAILABLE; missing valid rates are DEGRADED; authorization failures AUTH_FAILED; 429 RATE_LIMITED; other connectivity failures DEGRADED; operator-disabled agents DISABLED. Health includes last success/failure, latency, error class, counted retained requests and estimated cost. A successful listing is not proof that an inference request will succeed.

REAL, SIMULATED and UNAVAILABLE are explicit modes. Simulation is deterministic fixture behavior and does not prove cloud connectivity or independent model judgment. No fallback silently substitutes a model. Local support remains usable while cloud providers are unavailable. Transport errors retain error classes, not raw response bodies. Known local credentials and common key/bearer patterns are redacted before persistence; credential-bearing model inputs/outputs are rejected.

Structured-output formats follow [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs), [Anthropic structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs), [xAI structured outputs](https://docs.x.ai/developers/model-capabilities/text/structured-outputs), and [Ollama generate](https://docs.ollama.com/api/generate). Transport tests exercise these formats; live cloud compatibility remains unverified until credentials and models are configured.
