$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
function Assert-Exit([string]$Step) { if ($LASTEXITCODE -ne 0) { throw "$Step failed ($LASTEXITCODE)" } }
$VenvPython = Join-Path (Get-Location) '.venv/Scripts/python.exe'
& $VenvPython -m pip check
Assert-Exit 'Dependency consistency'
& $VenvPython -m ruff check app tests tools
Assert-Exit 'Lint'
& $VenvPython -m pytest
Assert-Exit 'Tests'
docker compose config --quiet
Assert-Exit 'Compose validation'
& $VenvPython tools/health_check.py
Assert-Exit 'Database health'
& $VenvPython tools/audit_foundation.py
Assert-Exit 'Foundation and secret audit'
git diff --check
Assert-Exit 'Whitespace check'
git status --short
Assert-Exit 'Git status'
docker compose ps
Assert-Exit 'Container inventory'
