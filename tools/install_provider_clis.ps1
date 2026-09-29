param()
$ErrorActionPreference = 'Stop'
$TriadRoot = Split-Path $PSScriptRoot -Parent
$ProviderPrefix = Join-Path $TriadRoot 'data/provider-cli'
if (!(Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
    throw 'Install Node.js from https://nodejs.org before installing provider CLIs'
}
# Pinned official vendor packages, local prefix only; no PATH or system-wide edits.
& npm.cmd install --prefix $ProviderPrefix --no-audit --no-fund '@openai/codex@0.155.0-alpha.2.6' '@anthropic-ai/claude-code@2.1.276' '@xai-official/grok@1.0.34'
if ($LASTEXITCODE -ne 0) { throw 'Provider CLI installation failed' }
Write-Output "Installed Triad-owned pinned provider CLIs under $ProviderPrefix. Open Settings / AI Providers and Refresh."
