param([int]$Port = 8000, [switch]$CoreOnly, [switch]$UpgradeDatabase)
$ErrorActionPreference = 'Stop'
$TriadRoot = Split-Path $PSScriptRoot -Parent
$TriadPython = Join-Path $TriadRoot '.venv/Scripts/python.exe'
if ($UpgradeDatabase) {
    Push-Location $TriadRoot
    try {
        & $TriadPython -m trading_core.upgrade
        if ($LASTEXITCODE -ne 0) { throw 'Database upgrade failed; existing services were not stopped' }
    } finally { Pop-Location }
}
$existing = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
foreach ($listener in $existing) {
    $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)"
    $launcher = Get-CimInstance Win32_Process -Filter "ProcessId = $($processInfo.ParentProcessId)"
    $isTriadLauncher = $launcher -and $launcher.ExecutablePath -eq $TriadPython
    if ($processInfo.CommandLine -notmatch 'uvicorn (triad.api|platform_host.api|trading_core.api):app' -or
        ($processInfo.ExecutablePath -notlike "$TriadRoot*" -and !$isTriadLauncher)) {
        throw "Port $Port belongs to another application; refusing to stop it"
    }
    Stop-Process -Id $listener.OwningProcess -ErrorAction Stop
}
$process = Start-Process -FilePath $TriadPython -ArgumentList '-m','uvicorn','platform_host.api:app','--host','127.0.0.1','--port',"$Port" -WorkingDirectory $TriadRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $TriadRoot 'logs/api.stdout.log') -RedirectStandardError (Join-Path $TriadRoot 'logs/api.stderr.log') -PassThru
$process.Id | Set-Content (Join-Path $TriadRoot 'logs/api.pid')
if (!$CoreOnly) {
    & (Join-Path $PSScriptRoot 'start_product.ps1') -Product triad
    & (Join-Path $PSScriptRoot 'start_product.ps1') -Product aegis
}
Write-Output "Core launched at http://127.0.0.1:$Port/core; products at /triad and /aegis"
