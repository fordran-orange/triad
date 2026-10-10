param([switch]$Install)
# Build the Aegis workstation UI (app/products/aegis/ui) into ui/dist, which the Aegis worker serves at /aegis/.
$ErrorActionPreference = 'Stop'
$Root = Split-Path $PSScriptRoot -Parent
$Ui = Join-Path $Root 'app/products/aegis/ui'
Set-Location $Ui
if ($Install -or -not (Test-Path (Join-Path $Ui 'node_modules'))) {
    npm ci --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw "npm ci failed ($LASTEXITCODE)" }
}
& (Join-Path $Root '.venv/Scripts/python.exe') (Join-Path $Root 'tools/aegis_contracts.py') --check
if ($LASTEXITCODE -ne 0) { throw 'ui/src/contracts.ts is stale; run tools/aegis_contracts.py and commit it' }
npm run build
if ($LASTEXITCODE -ne 0) { throw "UI build failed ($LASTEXITCODE)" }
Write-Output "Aegis UI built: $(Join-Path $Ui 'dist')"
