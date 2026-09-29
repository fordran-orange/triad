param(
    [switch]$SkipProviderInstall,
    [switch]$SkipSupervisorInstall,
    [switch]$NoMerge,
    [switch]$SyncRemote,
    [switch]$RunCycle
)

$ErrorActionPreference = 'Stop'
$TriadRoot = Split-Path $PSScriptRoot -Parent
$Python = Join-Path $TriadRoot '.venv\Scripts\python.exe'

function Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

Push-Location $TriadRoot
try {
    Step 'Verify canonical main checkout'
    $branch = (git branch --show-current).Trim()
    if ($LASTEXITCODE -ne 0) { throw 'Unable to determine current Git branch' }
    if ($branch -ne 'main') {
        throw "Milestone 1 must start from main; current branch is '$branch'"
    }
    $dirty = git status --porcelain
    if ($LASTEXITCODE -ne 0) { throw 'Unable to read Git status' }
    if ($dirty) {
        throw 'Working tree is not clean. Preserve or commit local changes before Milestone 1.'
    }

    if ($SyncRemote) {
        throw 'Review and reconcile remote changes separately before running this local launcher.'
    }

    Step 'Verify Python environment and deterministic dev tools'
    if (!(Test-Path $Python)) {
        throw "Missing Triad virtual environment: $Python"
    }
    & $Python -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'Installed dependencies are inconsistent; repair from requirements.lock before continuing' }
    & $Python -c 'import pytest, trading_core, ruff'
    if ($LASTEXITCODE -ne 0) { throw 'Required local development tools are missing' }

    if (-not $SkipProviderInstall) {
        Step 'Install Triad-owned pinned provider CLIs'
        & (Join-Path $PSScriptRoot 'install_provider_clis.ps1')
        if ($LASTEXITCODE -ne 0) { throw 'Provider CLI installation failed' }
    } else {
        Step 'Provider CLI installation skipped by operator'
    }

    Step 'Verify Core can start with its local dependencies'
    & (Join-Path $PSScriptRoot 'ensure_core.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'Core durability check failed' }

    if (-not $SkipSupervisorInstall) {
        Step 'Ensure Windows owns durable Core startup'
        try {
            # Idempotently reconcile the owned task to this accepted checkout.
            # A matching task name alone does not prove a current action or identity.
            & (Join-Path $PSScriptRoot 'install_core_supervisor.ps1')
            if ($LASTEXITCODE -ne 0) { throw 'Supervisor install returned failure' }
        } catch {
            throw "Core supervisor is required for Milestone 1 durability. Re-run PowerShell with sufficient rights or use -SkipSupervisorInstall only for diagnostic runs. $($_.Exception.Message)"
        }
    } else {
        Step 'Core supervisor installation skipped by operator (diagnostic only)'
    }

    Step 'Verify Triad product worker'
    $ProductHealthy = $false
    try {
        $ProductHealth = Invoke-RestMethod 'http://127.0.0.1:8101/health/live' -TimeoutSec 3
        $ProductHealthy = $ProductHealth.status -eq 'ok' -and $ProductHealth.product -eq 'triad'
    } catch { $ProductHealthy = $false }
    if (-not $ProductHealthy) {
        & (Join-Path $PSScriptRoot 'start_product.ps1') -Product triad
        if ($LASTEXITCODE -ne 0) { throw 'Triad worker launch failed' }
    }

    if (-not $RunCycle) {
        Write-Host 'Local startup checks finished. No model cycle was run. Use -RunCycle for the existing governed product proof.'
        return
    }
    Step 'Run REAL isolated product build with independent QA and Core merge gates'
    $rotationArgs = @((Join-Path $PSScriptRoot 'run_milestone1_rotation.py'))
    if ($NoMerge) { $rotationArgs += '--no-merge' }
    & $Python @rotationArgs
    if ($LASTEXITCODE -ne 0) {
        throw 'Governed product proof failed. Canonical evidence and any candidate worktree are retained.'
    }

    Step 'Milestone 1 rotation completed'
    if ($NoMerge) {
        Write-Host 'Diagnostic proof completed without merge because -NoMerge was supplied.'
    } else {
        Write-Host 'Independent QA, governed merge and restarted service checks passed. Broad host tool execution remains unverified.'
    }
} finally {
    Pop-Location
}
