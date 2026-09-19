# Claude Code

Installed locally using the official npm package, pinned to `2.1.276`, under
`C:\Triad\data\temp\provider-cli`. No system PATH changes were made.
The native executable is discovered directly from that prefix.

Login uses `claude auth login --claudeai`; status uses `claude auth status --json`.
Triad requires the reported Claude subscription method before labeling billing
SUBSCRIPTION. An installed key or successful version command is insufficient.
The process environment excludes Anthropic API keys and alternate billing settings.
The vendor owns its login; Triad never copies session credentials.

Claude subscription authentication is now verified. Version `2.1.276` is pinned
for the isolated adapter. Its trusted host harness has all built-in tools removed,
customization sources/hooks/skills/Chrome disabled, and exactly one ephemeral MCP
server. The host verifies that server's catalog before submitting a prompt.

The MCP file tools use `OfflineSandbox`: supplied text snapshots only, no host
mounts, no executor network, no credentials, and no arbitrary shell. Implementation
and proposal roles stage text changes under the governed improvement directories;
independent review still controls application to the repository. Each proposal is
limited to 12,000 UTF-8 bytes, with the existing file/line/output limits downstream.
Reviews cannot write. Reported file changes must match the sandbox export.

Real read-only README acceptance passed on 2026-09-18 using `claude-sonnet-5`
through the normal Triad runtime. See DAY5A_VERIFICATION.md for the proof.
The complete reviewed relay and fresh standalone connection checks remain pending.

Official references: [setup](https://code.claude.com/docs/en/setup) and
[CLI reference](https://code.claude.com/docs/en/cli-reference).
