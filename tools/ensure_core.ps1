param(
    [int]$Port = 8000,
    [string]$LogPath = "",
    [switch]$Restart,
    # Docker Desktop starts at sign-in and its engine follows about 12 s later; a pass that begins
    # first waits this long for the engine instead of failing on its pipe at once. 40 s keeps the
    # paper worst case of one pass (Ollama 30 s, compose 240 s, Core 90 s, two workers 100 s each)
    # inside the task's 10-minute limit (docs/CORE_DEPENDENCY_PORTS_AFTER_REBOOT.md, sections 2, 5).
    [ValidateRange(0, 300)][int]$EngineWaitSeconds = 40
)
$ErrorActionPreference = 'Stop'
# Core's cold start took 33 s on this laptop (2026-10-14); a 30 s wait logged a false recovery
# failure on every boot until the next pass five minutes later.
$CoreStartSeconds = 90
$TriadRoot = Split-Path $PSScriptRoot -Parent
if (-not $LogPath) { $LogPath = Join-Path $TriadRoot 'logs/core-supervisor.log' }
$LogDir = Split-Path $LogPath -Parent
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Write-SupervisorLog([string]$Message) {
    $line = "$(Get-Date -Format o) $Message"
    Add-Content -Path $LogPath -Value $line
}

function Test-CoreLive {
    try {
        $response = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health/live" -TimeoutSec 3
        return $response.status -eq 'ok'
    } catch {
        return $false
    }
}

function Invoke-Native([scriptblock]$Command) {
    # Under the preference 'Stop' a native command's stderr becomes a terminating error once it is
    # redirected; run the command with 'Continue' and hand back what it said and its exit code.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $lines = @(& $Command 2>&1 | ForEach-Object { "$_" })
        return @{ Lines = $lines; ExitCode = $LASTEXITCODE }
    } finally {
        $ErrorActionPreference = $previous
    }
}

function Test-DockerEngine {
    # The road compose takes to the engine; it fails in under a second while Docker Desktop is down.
    return (Invoke-Native { docker version --format '{{.Server.Version}}' }).ExitCode -eq 0
}

function Wait-DockerEngine([int]$Seconds) {
    if (Test-DockerEngine) { return $true }
    Write-SupervisorLog "Docker engine unavailable; waiting up to $Seconds s for Docker Desktop"
    $started = Get-Date
    while (((Get-Date) - $started).TotalSeconds -lt $Seconds) {
        Start-Sleep -Seconds 2
        if (Test-DockerEngine) {
            Write-SupervisorLog ("Docker engine available after {0:N0} s" -f ((Get-Date) - $started).TotalSeconds)
            return $true
        }
    }
    return $false
}

# Core liveness alone does not establish its local orchestrator dependency.
# Failure must not prevent recovery of Core diagnostics and the kill switch.
& (Join-Path $PSScriptRoot 'ensure_ollama.ps1')
$OllamaExit = $LASTEXITCODE

if ((Test-CoreLive) -and -not $Restart) {
    Write-SupervisorLog "Core healthy on port $Port"
    exit $OllamaExit
}

Write-SupervisorLog $(if ($Restart) { 'Core restart requested; ensuring database dependencies' } else { 'Core unavailable; ensuring database dependencies' })
Push-Location $TriadRoot
try {
    if (-not (Wait-DockerEngine $EngineWaitSeconds)) {
        throw "Docker engine unavailable after $EngineWaitSeconds s; Docker Desktop is not running"
    }

    $compose = Invoke-Native { docker compose up -d --wait --wait-timeout 240 }
    if ($compose.ExitCode -ne 0) {
        # Compose's own words, then Windows' excluded TCP ranges: a published port inside one of them
        # cannot bind (docs/CORE_DEPENDENCY_PORTS_AFTER_REBOOT.md, section 3.4), and the two lines
        # tell that apart from an engine that is down. Both were untimestamped in the launcher log.
        $said = @($compose.Lines | ForEach-Object { $_.Trim() } | Where-Object { $_ } | Select-Object -Last 20)
        foreach ($line in $said) { Write-SupervisorLog "compose: $line" }
        $ranges = @((Invoke-Native { netsh int ipv4 show excludedportrange protocol=tcp }).Lines |
            ForEach-Object { $_.Trim() } | Where-Object { $_ })
        Write-SupervisorLog ("excluded TCP port ranges: " + ($ranges -join ' | '))
        throw "docker compose dependency startup failed ($($compose.ExitCode))"
    }

    & (Join-Path $PSScriptRoot 'start_backend.ps1') -Port $Port -CoreOnly
    if ($LASTEXITCODE -ne 0) { throw "Core launch failed ($LASTEXITCODE)" }

    $deadline = (Get-Date).AddSeconds($CoreStartSeconds)
    do {
        Start-Sleep -Milliseconds 500
        if (Test-CoreLive) {
            Write-SupervisorLog "Core recovered and healthy on port $Port"
            exit $OllamaExit
        }
    } while ((Get-Date) -lt $deadline)

    throw "Core did not become healthy within $CoreStartSeconds seconds"
} catch {
    Write-SupervisorLog "Core recovery failed: $($_.Exception.Message)"
    exit 1
} finally {
    Pop-Location
}
