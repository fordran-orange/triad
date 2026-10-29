# Issue a product worker's key for its read-only Core reasoning route (Mission 14 spec §4.1).
# Writes <PRODUCT>_PRODUCT_KEY=<48 random URL-safe characters> into the repository's .env when none
# is set; -Rotate replaces an existing one. It never prints, logs or returns the key.
param(
    [Parameter(Mandatory)][ValidateSet('aegis')][string]$Product,
    [switch]$Rotate
)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$EnvFile = Join-Path $Root '.env'
$Name = ($Product.ToUpperInvariant()) + '_PRODUCT_KEY'

$lines = @()
if (Test-Path -LiteralPath $EnvFile) { $lines = @(Get-Content -LiteralPath $EnvFile -Encoding UTF8) }
$pattern = '^\s*' + [regex]::Escape($Name) + '\s*='
$existing = @($lines | Where-Object { $_ -match $pattern })
$hasKey = $existing | Where-Object { ($_ -replace $pattern, '').Trim().Length -ge 32 }
if ($hasKey -and -not $Rotate) {
    Write-Output "$Name already issued; use -Rotate to replace it"
    return
}

$alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_'
$bytes = New-Object byte[] 48
# Create().GetBytes works on Windows PowerShell 5.1 (.NET Framework) and PowerShell 7 alike.
$random = [System.Security.Cryptography.RandomNumberGenerator]::Create()
$random.GetBytes($bytes)
$random.Dispose()
$key = -join ($bytes | ForEach-Object { $alphabet[$_ % 64] })

$kept = @($lines | Where-Object { $_ -notmatch $pattern })
$kept += "$Name=$key"
[System.IO.File]::WriteAllLines($EnvFile, [string[]]$kept, (New-Object System.Text.UTF8Encoding($false)))
Remove-Variable key, bytes
if ($hasKey) { Write-Output "$Name rotated" } else { Write-Output "$Name issued" }
