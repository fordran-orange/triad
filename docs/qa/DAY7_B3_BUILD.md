# B3 default allocation and transport build

New starting defaults: 8192 reasoning, 24000 input characters, 6144 output tokens, 480 seconds, 60 tool operations. Reasoning and final output are independent. Compact Qwen helper tasks retain explicit small allocations.

Migration013 adds an immutable versioned policy overlay for legacy static agents without rewriting definitions, WorkItems or historical results. Known old default controls are raised once; deliberately lowered/custom values and all cost/authority controls are retained. Apply with the explicit database-upgrade command after independent QA. Rollback needs the preserved database backup or a reviewed policy rollback before old validators run; simply launching old code on the new configuration is not a verified rollback.

Input assembly/routing preserves context up to the physical serialization limit; dispatch obtains governed extensions before provider invocation. HTTP output exhaustion is a resource-blocked outcome and creates a governed request when running under Core. Incomplete structured responses cannot resume in place: no automatic duplicate billable request is made. HTTP cancellation returns control promptly; late outputs remain rejected by the host epoch/kill checks. Local Ollama checks actual model context capacity before generating and sizes context conservatively instead of silently truncating to4096.

Provider-reported reasoning tokens are checked when supplied. Native vendor harnesses do not consistently expose a separate reasoning count; unknown remains null. The generic reasoning-extension contract is supported; no claim that8192 is an enforceable vendor-native thinking knob. Output+reasoning billing remains conservatively covered by provider output accounting; there is no new API spend authority.

Root targeted tests and independent review evidence are recorded alongside this report. No production migration/restart has occurred for B3.
