param(
    [switch]$SkipProviderInstall,
    [switch]$SkipSupervisorInstall,
    [switch]$NoMerge
)

$ErrorActionPreference = 'Stop'
$TriadRoot = Split-Path $PSScriptRoot -Parent
$Python = Join-Path $TriadRoot '.venv\Scripts\python.exe'
$Pip = Join-Path $TriadRoot '.venv\Scripts\pip.exe'

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

    Step 'Fast-forward to current origin/main'
    git fetch origin
    if ($LASTEXITCODE -ne 0) { throw 'git fetch origin failed' }
    git pull --ff-only origin main
    if ($LASTEXITCODE -ne 0) { throw 'main cannot fast-forward cleanly to origin/main' }

    Step 'Verify Python environment and deterministic dev tools'
    if (!(Test-Path $Python)) {
        throw "Missing Triad virtual environment: $Python"
    }
    & $Python -m pip install -e '.[dev]'
    if ($LASTEXITCODE -ne 0) { throw 'Triad development dependency install failed' }

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
            $task = Get-ScheduledTask -TaskName 'Triad Core Supervisor' -ErrorAction SilentlyContinue
            if (-not $task) {
                & (Join-Path $PSScriptRoot 'install_core_supervisor.ps1')
                if ($LASTEXITCODE -ne 0) { throw 'Supervisor install returned failure' }
            } else {
                Write-Host "Triad Core Supervisor already installed."
            }
        } catch {
            throw "Core supervisor is required for Milestone 1 durability. Re-run PowerShell with sufficient rights or use -SkipSupervisorInstall only for diagnostic runs. $($_.Exception.Message)"
        }
    } else {
        Step 'Core supervisor installation skipped by operator (diagnostic only)'
    }

    Step 'Run REAL Grok -> Claude -> Codex Milestone 1 rotation'
    $rotationArgs = @((Join-Path $PSScriptRoot 'run_milestone1_rotation.py'))
    if ($NoMerge) { $rotationArgs += '--no-merge' }
    & $Python @rotationArgs
    if ($LASTEXITCODE -ne 0) {
        throw 'Milestone 1 provider rotation failed. The run branch/worktree is retained as evidence.'
    }

    Step 'Milestone 1 rotation completed'
    if ($NoMerge) {
        Write-Host 'Diagnostic proof completed without merge because -NoMerge was supplied.'
    } else {
        Write-Host 'Machine gates passed and the autonomous run merged to main.'
    }
} finally {
    Pop-Location
}
