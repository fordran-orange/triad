param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
function Assert-Exit([string]$Step) { if ($LASTEXITCODE -ne 0) { throw "$Step failed ($LASTEXITCODE)" } }
if (!(Test-Path '.venv/Scripts/python.exe')) {
    & $Python -c "import sys; assert (3,12) <= sys.version_info[:2] < (3,14), 'Requires Python 3.12 or 3.13'"
    Assert-Exit 'Python version'
    & $Python -m venv .venv
    Assert-Exit 'Virtual environment'
}
$VenvPython = Join-Path (Get-Location) '.venv/Scripts/python.exe'
& $VenvPython -m pip install -r requirements.lock
Assert-Exit 'Locked dependencies'
& $VenvPython -m pip install --no-deps --no-build-isolation -e '.[dev]'
Assert-Exit 'Project install'
& $VenvPython tools/init_env.py
Assert-Exit 'Local configuration'
docker compose config --quiet
Assert-Exit 'Compose configuration'
docker compose up -d --wait --wait-timeout 240
Assert-Exit 'Database services'
& $VenvPython tools/init_graph.py
Assert-Exit 'Graph constraints'
& $VenvPython -m pytest
Assert-Exit 'Automated tests'
& $VenvPython tools/health_check.py
Assert-Exit 'Authenticated health checks'
