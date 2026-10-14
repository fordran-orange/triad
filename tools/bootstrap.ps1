# Build the local installation (Mission 7 spec §3.1): one Core codebase and runtime, three
# dependency environments built from their lock files, each an editable install of the same app/.
#   .venv        Core and the gateway   requirements.lock        extras dev
#   .venv-triad  the Triad worker       requirements-triad.lock  extras dev,triad
#   .venv-aegis  the Aegis worker       requirements-aegis.lock  extras dev,aegis
# -Product builds one environment only and skips the shared steps.
param(
    [string]$Python = 'python',
    [ValidateSet('all', 'core', 'triad', 'aegis')][string]$Product = 'all'
)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
function Assert-Exit([string]$Step) { if ($LASTEXITCODE -ne 0) { throw "$Step failed ($LASTEXITCODE)" } }

# The base interpreter: the one .venv was made from (pyvenv.cfg "home"), else -Python. PATH's
# python may be another version on this host.
function Resolve-BaseInterpreter {
    $Config = '.venv/pyvenv.cfg'
    $Base = $Python
    if (Test-Path $Config) {
        $HomeLine = Get-Content $Config | Where-Object { $_ -match '^\s*home\s*=' } | Select-Object -First 1
        if ($HomeLine) { $Base = Join-Path (($HomeLine -split '=', 2)[1].Trim()) 'python.exe' }
    }
    & $Base -c "import sys; assert (3,12) <= sys.version_info[:2] < (3,14), 'Requires Python 3.12 or 3.13'"
    Assert-Exit "Python version ($Base)"
    return $Base
}

function New-Environment([string]$Name, [string]$Lock, [string]$Extras) {
    if (!(Test-Path "$Name/Scripts/python.exe")) {
        & $script:Base -m venv $Name
        Assert-Exit "Virtual environment $Name"
    }
    $EnvPython = Join-Path (Get-Location) "$Name/Scripts/python.exe"
    & $EnvPython -m pip install -r $Lock
    Assert-Exit "Locked dependencies ($Lock)"
    & $EnvPython -m pip install --no-deps --no-build-isolation -e ".[$Extras]"
    Assert-Exit "Project install ($Name)"
    & $EnvPython -m pip check
    Assert-Exit "Dependency consistency ($Name)"
}

$script:Base = Resolve-BaseInterpreter
if ($Product -in @('all', 'core')) { New-Environment '.venv' 'requirements.lock' 'dev' }
if ($Product -in @('all', 'triad')) { New-Environment '.venv-triad' 'requirements-triad.lock' 'dev,triad' }
if ($Product -in @('all', 'aegis')) { New-Environment '.venv-aegis' 'requirements-aegis.lock' 'dev,aegis' }
if ($Product -ne 'all') { Write-Output "Built the $Product environment."; exit 0 }

# Shared steps run once, from Core's environment: one database set, one Core runtime.
$VenvPython = Join-Path (Get-Location) '.venv/Scripts/python.exe'
& $VenvPython tools/init_env.py
Assert-Exit 'Local configuration'
docker compose config --quiet
Assert-Exit 'Compose configuration'
docker compose up -d --wait --wait-timeout 240
Assert-Exit 'Database services'
& $VenvPython tools/init_graph.py
Assert-Exit 'Graph constraints'
& $VenvPython tools/day2.py init
Assert-Exit 'Orchestration migration and projections'
& $VenvPython tools/day3.py init
Assert-Exit 'Autonomy runtime migration'
& $VenvPython tools/day4.py init
Assert-Exit 'Durable cycle jobs migration'
& (Join-Path $PSScriptRoot 'verify.ps1')
Assert-Exit 'Verification (tools/verify.ps1)'
& $VenvPython tools/health_check.py
Assert-Exit 'Authenticated health checks'
