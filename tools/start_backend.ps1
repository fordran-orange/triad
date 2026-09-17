param([int]$Port = 8000)
$ErrorActionPreference = 'Stop'
$TriadRoot = Split-Path $PSScriptRoot -Parent
$TriadPython = Join-Path $TriadRoot '.venv/Scripts/python.exe'
$existing = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
foreach ($listener in $existing) {
    $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)"
    $launcher = Get-CimInstance Win32_Process -Filter "ProcessId = $($processInfo.ParentProcessId)"
    $isTriadLauncher = $launcher -and $launcher.ExecutablePath -eq $TriadPython
    if ($processInfo.CommandLine -notmatch 'uvicorn triad.api:app' -or
        ($processInfo.ExecutablePath -notlike "$TriadRoot*" -and !$isTriadLauncher)) {
        throw "Port $Port belongs to another application; refusing to stop it"
    }
    Stop-Process -Id $listener.OwningProcess -ErrorAction Stop
}
$process = Start-Process -FilePath $TriadPython -ArgumentList '-m','uvicorn','triad.api:app','--host','127.0.0.1','--port',"$Port" -WorkingDirectory $TriadRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $TriadRoot 'logs/api.stdout.log') -RedirectStandardError (Join-Path $TriadRoot 'logs/api.stderr.log') -PassThru
$process.Id | Set-Content (Join-Path $TriadRoot 'logs/api.pid')
Write-Output "Backend launched at http://127.0.0.1:$Port; verify /health/live and /api/status"
