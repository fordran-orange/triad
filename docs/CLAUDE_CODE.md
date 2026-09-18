# Claude Code

Installed locally using the official npm package, pinned to `2.1.276`, under
`C:\Triad\data\temp\provider-cli`. No system PATH changes were made.
The native executable is discovered directly from that prefix.

Login uses `claude auth login --claudeai`; status uses `claude auth status --json`.
Triad requires the reported Claude subscription method before labeling billing
SUBSCRIPTION. An installed key or successful version command is insufficient.
The process environment excludes Anthropic API keys and alternate billing settings.
The vendor owns its login; Triad never copies session credentials.

Claude is not authenticated in the current verification. Native WorkItem execution
also remains blocked on the unimplemented outer isolation layer; login alone is
not enough. The architecture-document acceptance WorkItem has not run.

Official references: [setup](https://code.claude.com/docs/en/setup) and
[CLI reference](https://code.claude.com/docs/en/cli-reference).
