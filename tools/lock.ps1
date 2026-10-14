# Freeze one environment into its lock file (Mission 7 spec §3.1). The locks are the truth that
# tools/bootstrap.ps1 builds from; regenerate them only through this script.
#   tools\lock.ps1 -Product core|triad|aegis          write the lock from the environment
#   tools\lock.ps1 -Product aegis -Check               exit 1 when the environment and lock differ
param(
    [ValidateSet('core', 'triad', 'aegis')][string]$Product = 'core',
    [switch]$Check
)
$ErrorActionPreference = 'Stop'
$Root = Split-Path $PSScriptRoot -Parent
$Environment = if ($Product -eq 'core') { '.venv' } else { ".venv-$Product" }
$LockName = if ($Product -eq 'core') { 'requirements.lock' } else { "requirements-$Product.lock" }
$Python = Join-Path $Root "$Environment/Scripts/python.exe"
if (!(Test-Path -LiteralPath $Python)) { throw "Missing ${Python}: run tools/bootstrap.ps1 -Product $Product" }

$Frozen = & $Python -m pip freeze --exclude-editable
if ($LASTEXITCODE -ne 0) { throw "pip freeze failed in $Environment ($LASTEXITCODE)" }
$Lines = [string[]]($Frozen | Where-Object { $_ -match '==' } | ForEach-Object { $_.Trim() })
[Array]::Sort($Lines, [StringComparer]::OrdinalIgnoreCase)
$Text = ($Lines -join "`n") + "`n"
$LockPath = Join-Path $Root $LockName

if ($Check) {
    $Current = if (Test-Path -LiteralPath $LockPath) { [IO.File]::ReadAllText($LockPath) -replace "`r`n", "`n" } else { '' }
    if ($Current -ne $Text) {
        Write-Output "$LockName differs from $Environment"
        exit 1
    }
    Write-Output "$LockName matches $Environment ($($Lines.Count) pins)"
    exit 0
}
[IO.File]::WriteAllText($LockPath, $Text)
Write-Output "$LockName written from $Environment ($($Lines.Count) pins)"
