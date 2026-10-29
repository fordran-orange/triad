# Verify the installation (Mission 7 spec §3.4): one Core runtime, three dependency environments,
# each test scope run on its own interpreter. Exit 0 only when every step and all three scopes
# pass in full; the closing line "... all three scopes green" is printed only then.
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
function Assert-Exit([string]$Step) { if ($LASTEXITCODE -ne 0) { throw "$Step failed ($LASTEXITCODE)" } }

# Inherited pytest options could narrow every scope below (review finding 1); verification runs
# the scopes as they are.
foreach ($Name in @('PYTEST_ADDOPTS', 'PYTEST_PLUGINS')) {
    $Value = [Environment]::GetEnvironmentVariable($Name, 'Process')
    if ($Value) { Write-Output "cleared inherited ${Name}: $Value" }
}
Remove-Item Env:PYTEST_ADDOPTS -ErrorAction SilentlyContinue
Remove-Item Env:PYTEST_PLUGINS -ErrorAction SilentlyContinue

$Scopes = [ordered]@{ core = '.venv'; triad = '.venv-triad'; aegis = '.venv-aegis' }
$Interpreters = @{}
foreach ($Scope in $Scopes.Keys) {
    $Python = Join-Path (Get-Location) "$($Scopes[$Scope])/Scripts/python.exe"
    if (!(Test-Path -LiteralPath $Python)) { throw "Missing ${Python}: run tools/bootstrap.ps1 -Product $Scope" }
    $Interpreters[$Scope] = $Python
    & $Python -m pip check
    Assert-Exit "Dependency consistency ($Scope)"
    & (Join-Path $PSScriptRoot 'lock.ps1') -Product $Scope -Check
    Assert-Exit "Lock ($Scope): the environment differs from its lock file; rebuild it with tools/bootstrap.ps1 -Product $Scope or refreeze it with tools/lock.ps1 -Product $Scope"
}
$CorePython = $Interpreters['core']

# Lint gate: the Aegis scope and every Python file the dependency environments touched. The
# repository-wide count predates them and is reported, not gated (plan ruling P3).
$Lint = @('app/products/aegis', 'tests/products/aegis', 'tools/aegis_contracts.py',
    'tests/conftest.py', 'tests/test_pytest_scope.py', 'tests/test_environments.py',
    'tests/test_architecture.py', 'tests/test_day8_workflow_qa.py',
    'tools/run_daily_product_cycle.py', 'tools/accept_environments.py',
    'tests/test_lab_store.py', 'tests/test_lab_query.py', 'tests/test_lab_sharpe.py',
    'tests/test_lab_identity.py', 'tests/test_lab_blocks.py', 'tests/test_lab_tasks.py', 'tools/aegis_decompact.py') +
    @(Get-ChildItem tests/test_aegis_*.py | ForEach-Object { $_.FullName })
& $CorePython -m ruff check @Lint
Assert-Exit 'Lint'
& $CorePython -m ruff format --check @Lint
Assert-Exit 'Format'
$RepoWide = @(& $CorePython -m ruff check app tests tools --output-format concise --exit-zero | Where-Object { $_ -match ':\d+:\d+: ' }).Count
Write-Output "repo-wide ruff (reported, not a gate): $RepoWide findings"

# Ownership: every collected test belongs to exactly one scope; each scope must run all it owns.
try {
    $env:TRIAD_PYTEST_SCOPE = 'inventory'
    $Collected = & $CorePython -m pytest --collect-only -q -p no:cacheprovider
    Assert-Exit 'Inventory'
    $Inventory = ($Collected | Select-String '^inventory: ').Line
    Write-Output $Inventory
    $Owned = @{}
    foreach ($Match in [regex]::Matches($Inventory, '(core|triad|aegis) (\d+)')) { $Owned[$Match.Groups[1].Value] = [int]$Match.Groups[2].Value }

    $Summary = [ordered]@{}
    foreach ($Scope in $Scopes.Keys) {
        $env:TRIAD_PYTEST_SCOPE = $Scope
        Write-Output "== scope $Scope on $($Scopes[$Scope]) =="
        & $Interpreters[$Scope] -m pytest -q -p no:cacheprovider | Tee-Object -Variable Run
        Assert-Exit "Tests ($Scope)"
        $Line = ($Run | Select-String "^scope ${Scope}: ").Line
        $Full = [regex]::Match("$Line", "^scope ${Scope}: (\d+) run, the full scope;")
        if (!$Full.Success) { throw "Scope $Scope did not run as a full scope: $Line" }
        $Ran = [int]$Full.Groups[1].Value
        if ($Ran -ne $Owned[$Scope]) { throw "Scope $Scope ran $Ran tests but owns $($Owned[$Scope])" }
        $Summary[$Scope] = ($Run | Select-String '\d+ passed' | Select-Object -Last 1).Line.Trim(' =')
    }
} finally {
    Remove-Item Env:TRIAD_PYTEST_SCOPE -ErrorAction SilentlyContinue
}

docker compose config --quiet
Assert-Exit 'Compose validation'
& $CorePython tools/health_check.py
Assert-Exit 'Database health'
& $CorePython tools/audit_foundation.py
Assert-Exit 'Foundation and secret audit'
git diff --check
Assert-Exit 'Whitespace check'
git status --short
Assert-Exit 'Git status'
docker compose ps
Assert-Exit 'Container inventory'

Write-Output ("core: {0}; triad: {1}; aegis: {2}; all three scopes green" -f $Summary['core'], $Summary['triad'], $Summary['aegis'])
