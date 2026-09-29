param(
    [int]$Port = 8000,
    [string]$LogPath = "",
    [switch]$Restart
)
$ErrorActionPreference = 'Stop'
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

if ((Test-CoreLive) -and -not $Restart) {
    Write-SupervisorLog "Core healthy on port $Port"
    exit 0
}

Write-SupervisorLog $(if ($Restart) { 'Core restart requested; ensuring database dependencies' } else { 'Core unavailable; ensuring database dependencies' })
Push-Location $TriadRoot
try {
    docker compose up -d --wait --wait-timeout 240 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "docker compose dependency startup failed ($LASTEXITCODE)" }

    & (Join-Path $PSScriptRoot 'start_backend.ps1') -Port $Port -CoreOnly
    if ($LASTEXITCODE -ne 0) { throw "Core launch failed ($LASTEXITCODE)" }

    $deadline = (Get-Date).AddSeconds(30)
    do {
        Start-Sleep -Milliseconds 500
        if (Test-CoreLive) {
            Write-SupervisorLog "Core recovered and healthy on port $Port"
            exit 0
        }
    } while ((Get-Date) -lt $deadline)

    throw 'Core did not become healthy within 30 seconds'
} catch {
    Write-SupervisorLog "Core recovery failed: $($_.Exception.Message)"
    exit 1
} finally {
    Pop-Location
}
