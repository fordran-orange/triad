param(
    [ValidateRange(1, 180)][int]$TimeoutSeconds = 30,
    [string]$LogPath = ''
)
$ErrorActionPreference = 'Stop'
$TriadRoot = Split-Path $PSScriptRoot -Parent
if (!$LogPath) { $LogPath = Join-Path $TriadRoot 'logs/ollama-supervisor.log' }
New-Item -ItemType Directory -Force -Path (Split-Path $LogPath -Parent) | Out-Null

function Write-OllamaLog([string]$Message) {
    Add-Content -LiteralPath $LogPath -Value "$(Get-Date -Format o) $Message"
}

function Get-TriadOllamaSetting([string]$Name, [string]$Default) {
    $value = [Environment]::GetEnvironmentVariable($Name, 'Process')
    if ($value) { return $value }
    $dotenv = Join-Path $TriadRoot '.env'
    if (Test-Path -LiteralPath $dotenv) {
        foreach ($line in Get-Content -LiteralPath $dotenv) {
            if ($line -match ('^\s*' + [regex]::Escape($Name) + '\s*=\s*(.*?)\s*$')) {
                $Default = $Matches[1].Trim('"', "'")
            }
        }
    }
    return $Default
}

function Get-LocalOllamaUri([string]$Value) {
    if ($Value -notmatch '^https?://') { $Value = 'http://' + $Value }
    try { $uri = [uri]$Value } catch { throw 'Ollama endpoint is malformed' }
    if (!$uri.IsAbsoluteUri -or $uri.Scheme -ne 'http' -or
        $uri.Host -notin @('127.0.0.1', 'localhost', '[::1]', '::1') -or
        $uri.UserInfo -or $uri.Query -or $uri.Fragment -or $uri.AbsolutePath -ne '/') {
        throw 'Ollama supervisor requires an HTTP loopback endpoint without credentials, query or path'
    }
    return $uri
}

function Get-OllamaTags([uri]$Endpoint) {
    try {
        $tags = Invoke-RestMethod -Uri ($Endpoint.AbsoluteUri.TrimEnd('/') + '/api/tags') -TimeoutSec 3 -MaximumRedirection 0
        if ($null -eq $tags -or $null -eq $tags.PSObject.Properties['models']) { return $null }
        return $tags
    } catch { return $null }
}

try {
    $endpoint = Get-LocalOllamaUri (Get-TriadOllamaSetting 'OLLAMA_URL' 'http://127.0.0.1:11434')
    $model = Get-TriadOllamaSetting 'OLLAMA_MODEL' 'qwen3:4b'
    # Scheduled processes may retain an old environment. Read the current user's
    # persistent model location and host instead of moving or redownloading models.
    $configuredHost = [Environment]::GetEnvironmentVariable('OLLAMA_HOST', 'User')
    if (!$configuredHost) { $configuredHost = $env:OLLAMA_HOST }
    if ($configuredHost) {
        $hostUri = Get-LocalOllamaUri $configuredHost
        if ($hostUri.Port -ne $endpoint.Port -or $hostUri.Host -ne $endpoint.Host) {
            throw 'OLLAMA_HOST and Triad OLLAMA_URL disagree; refusing to launch on a different endpoint'
        }
    }
    $tags = Get-OllamaTags $endpoint
    if (!$tags) {
        $listener = Get-NetTCPConnection -LocalPort $endpoint.Port -State Listen -ErrorAction SilentlyContinue
        if ($listener) { throw 'Configured Ollama port is occupied but its model API is unavailable; no process was stopped' }
        $binary = Join-Path $env:LOCALAPPDATA 'Programs/Ollama/ollama.exe'
        if (!(Test-Path -LiteralPath $binary -PathType Leaf)) {
            throw 'Ollama executable is missing from the current user installation; install or repair explicitly'
        }
        $modelPath = [Environment]::GetEnvironmentVariable('OLLAMA_MODELS', 'User')
        if (!$modelPath) { $modelPath = $env:OLLAMA_MODELS }
        if ($modelPath) {
            $modelPath = [Environment]::ExpandEnvironmentVariables($modelPath)
            if (!(Test-Path -LiteralPath $modelPath -PathType Container)) {
                throw 'Configured OLLAMA_MODELS directory is missing; refusing to use a different model store'
            }
        }
        $oldHost = $env:OLLAMA_HOST
        $oldModels = $env:OLLAMA_MODELS
        try {
            $env:OLLAMA_HOST = $endpoint.Authority
            if ($modelPath) { $env:OLLAMA_MODELS = $modelPath }
            $stamp = Get-Date -Format 'yyyyMMddTHHmmssfff'
            $process = Start-Process -FilePath $binary -ArgumentList 'serve' -WindowStyle Hidden -PassThru `
                -WorkingDirectory (Split-Path $binary -Parent) `
                -RedirectStandardOutput (Join-Path (Split-Path $LogPath -Parent) "ollama-$stamp.stdout.log") `
                -RedirectStandardError (Join-Path (Split-Path $LogPath -Parent) "ollama-$stamp.stderr.log")
            Write-OllamaLog "Started existing Ollama installation hidden (PID $($process.Id))"
        } finally {
            $env:OLLAMA_HOST = $oldHost
            $env:OLLAMA_MODELS = $oldModels
        }
        $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
        do {
            Start-Sleep -Milliseconds 500
            $tags = Get-OllamaTags $endpoint
            if ($tags) { break }
        } while ((Get-Date) -lt $deadline)
        if (!$tags) { throw 'Ollama model API did not become available within the startup deadline' }
    }
    if ($model -notin @($tags.models | ForEach-Object { $_.name })) {
        throw 'Ollama is running but the configured Triad model is absent; no model was pulled or changed'
    }
    Write-OllamaLog 'Ollama model API available and configured Triad model installed; no inference performed'
    exit 0
} catch {
    Write-OllamaLog "Ollama recovery failed: $($_.Exception.Message)"
    exit 1
}
