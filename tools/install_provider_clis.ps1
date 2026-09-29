param()
$ErrorActionPreference = 'Stop'
$TriadRoot = Split-Path $PSScriptRoot -Parent
$ProviderPrefix = Join-Path $TriadRoot 'data/provider-cli'
$NpmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
$NpmPath = if ($NpmCommand) { $NpmCommand.Source } else { Join-Path $env:ProgramFiles 'nodejs/npm.cmd' }
if (!(Test-Path -LiteralPath $NpmPath)) {
    throw 'Install Node.js from https://nodejs.org before installing provider CLIs'
}
# Pinned official vendor packages, local prefix only; no PATH or system-wide edits.
& $NpmPath install --prefix $ProviderPrefix --no-audit --no-fund '@openai/codex@0.155.0-alpha.2.6' '@anthropic-ai/claude-code@2.1.276' '@xai-official/grok@1.0.34'
if ($LASTEXITCODE -ne 0) { throw 'Provider CLI installation failed' }
# Verify all package entry points before declaring a usable installation.
foreach ($Entry in @('@openai/codex/bin/codex.js', '@xai-official/grok/bin/grok')) {
    if (!(Test-Path -LiteralPath (Join-Path $ProviderPrefix "node_modules/$Entry"))) {
        throw "Provider package entry point missing: $Entry"
    }
}
$ClaudeNative = Join-Path $ProviderPrefix 'node_modules/@anthropic-ai/claude-code/bin/claude.exe'
$ClaudeScript = Join-Path $ProviderPrefix 'node_modules/@anthropic-ai/claude-code/cli.js'
if (!(Test-Path -LiteralPath $ClaudeNative) -and !(Test-Path -LiteralPath $ClaudeScript)) {
    throw 'Claude package entry point missing'
}
Write-Output "Installed Triad-owned pinned provider CLIs under $ProviderPrefix. Open Settings / AI Providers and Refresh."
