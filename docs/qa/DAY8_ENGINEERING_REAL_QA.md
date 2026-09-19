# Day 8 real isolated engineering capability acceptance

**Verdict: PASS for the exact capability proposal and role-overlay scope below.** Reviewer: `/root/day6_qa_b`, independent of the builder. This is an evidence audit of one actual provider run, not a new provider execution or a product merge approval.

## Revision and prior security QA

Actual probe base: `2cc4bedcdb658ea9205f8640ac00992cd3a5c0a6`. All 15 applicable implementation files at that revision match the combined independently reviewed engineering foundation (`b43054bb704c36ea53b380b5b65041258aa94333`) and corrected immutable role/probe overlay (`5faaec90492d8fe0d1994f14942901184e1b1f92`) manifests. Their earlier failure reports remain preserved. The role correction independently passed nine cases; the engineering correction passed 51 cases plus the two corrected QA-only native-result fixtures. No additional vendor calls, production writes, restarts, or implementation edits were made for this acceptance audit.

## Canonical evidence checked read-only

- EngineeringProbeResult `72fa7db2-244e-4ee0-8d25-6d17b8dbe066` matches the saved probe report, including staged bytes, grant, Usage, native event and offline checks.
- Work `b66984e4-73ad-40d9-b26d-26f1e0997faf`: Triad-owned, CLAUDE builder, distinct CODEX reviewer, tier 2, `read` and `write_code`, AWAITING_REVIEW. Original RunAuthority, request and grant all retain epoch 2. Scope digest: `e081863bfe0c05669abdf9cb693e3f791c458851c8a223eb89af38f55d93c14c`.
- Run `404a9c1a-76ab-4a86-8e34-d80cb050279e`; Usage `eed83885-4f01-4ba4-9040-f773b5d81a26`: REAL/SUCCESS, anthropic / claude_code_cli, actual model `claude-sonnet-5`, subscription billing, 11,037 measured input tokens and 856 measured output tokens, 13.75 seconds. Reasoning tokens remain unknown, not fabricated.
- Native event `6cdd54ef-2115-4d13-899c-d141b3374838`: one observed `propose_file_change` call, zero denials, DOCKER_OFFLINE_TOOLS. Its model and token measurements agree with Usage.
- Exactly one authorized path, `app/products/triad/features/engineering_probe.html`, contains `<h1>Isolated engineering probe</h1>` followed by a newline. Independently recomputed SHA-256: `fb43bb4fb91cb8a8bab1846415671014099a888ad93771a7cde3b085994a8af6`. This equals the check snapshot and reported file hash.
- Fixed check `day8-ui-probe-v1` returned PASS / exit 0, empty stderr, and `PASS: actual isolated staged UI asset`. Its script digest was independently reconstructed as `77638e08e334e33c1560d9f0e244356f5a6ebf95c89445288e9242c08b58fb6d`; image was `python@sha256:9d2e5553305c7c7b0097999bb17187c69b921ccd6bc9d40e4bb5ebe652c00285`. The reviewed checker executes fixed host-authored assertions inside the isolated environment.
- Probe plan records current text-substrate version `f06f3a4e-8c64-4650-a562-9a217e0ead24`, still current VERIFIED/AVAILABLE for the same provider, model and transport. This explicitly authorized capability experiment did not pretend the new editing capability had already been verified or routed.
- Probe asset is absent from the host working tree and HEAD. Result says `merged: false`; the work awaits review. At audit time the original proposal remains CLAIMED/RESTRICTED, the current registry has no AVAILABLE `isolated_product_ui_edit`, and neither the stored nor effective CLAUDE definition includes `write_code`.

Read-only canonical snapshot: `logs/day8-real-probe-independent.json`. Saved actual report SHA-256: `3818edcdfa78a4a0fec999f455cfed0a72cc34eacd991d06b0881fa55f7d3a84`.

## Exact independently accepted proposal

The payload in `logs/day8-capability-adoption-candidate.json` validates as Capability and its normalized canonical fingerprint is:

`ed98a219b9256fbedb3e0402d7c43caf1349815188f846ef430c3c1b49fab924`

Capability ID `2c36eeea-c6e6-4ce7-a126-2df4850506c5`: anthropic / claude-sonnet-5 / claude_code_cli / `isolated_product_ui_edit`, tool-mediated, AVAILABLE/VERIFIED, required permission `write_code`. Its dated evidence points to the actual probe result, run and exact report hash. This independent acceptance permits the Core governed proposal/adoption process to use that exact payload; it does not itself modify the registry.

The accepted role marker is **`engineering-role:CLAUDE:isolated_product_ui_edit`**, for the reviewed overlay implementation at `5faaec9`. Existing CLAUDE member only; unchanged stored base-definition digest `b3e9ac4e351ce61d320260fae47530466853605565a39a42412c6d53aec0cfbb`. The effective overlay may add only `write_code` and the named capability, contingent on exact build/QA and current capability version. Tier, existing tools, paths and budgets remain unchanged. Capability downgrade, replacement, failing/replaced QA or a base-definition mismatch invalidates the effective extension until reviewed adoption is renewed.

## Limits of this acceptance

The real probe directly demonstrates one HTML file staged through the reviewed exact-asset mechanism and checked offline. JS/CSS use shares that reviewed mediation but has not been functionally demonstrated by this probe; each product change still requires its own fixed checks and independent QA. This does not verify browser behavior, JavaScript functionality, general repository editing, backend changes, host shell, provider-selected test execution, Git authority, network access from staged tools, or general MCP capability. The capability maximum remains three files, 600 lines and 32,000 bytes, with Core granting exact product-feature HTML/JS/CSS paths for each work item. Subscription provider communication is distinct from the offline staging/test boundary.

No blocker was found for adoption of this exact narrow capability and reviewed overlay. The real product cycle, its independent provider QA, exact governed merge, and post-merge checks remain separate acceptance gates.
