param([ValidateSet('triad','aegis')][string]$Product)
$ErrorActionPreference = 'Stop'
$TradingRoot = Split-Path $PSScriptRoot -Parent
$TradingPython = Join-Path $TradingRoot '.venv/Scripts/python.exe'
$ProductPort = if ($Product -eq 'triad') {8101} else {8102}
$ProductApp = "products.$Product.server:app"
$listeners = Get-NetTCPConnection -LocalPort $ProductPort -State Listen -ErrorAction SilentlyContinue
foreach ($listener in $listeners) {
    $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)"
    $ExpectedWorker = $processInfo.CommandLine -match [regex]::Escape("uvicorn $ProductApp")
    $LegacyAegisWorker = $Product -eq 'aegis' -and $processInfo.CommandLine -match 'uvicorn products\.p2p\.server:app'
    if (!$ExpectedWorker -and !$LegacyAegisWorker) {
        throw "Port $ProductPort belongs to another application"
    }
    Stop-Process -Id $listener.OwningProcess
}
$process = Start-Process -FilePath $TradingPython -ArgumentList '-m','uvicorn',$ProductApp,'--host','127.0.0.1','--port',"$ProductPort" -WorkingDirectory $TradingRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $TradingRoot "logs/$Product.stdout.log") -RedirectStandardError (Join-Path $TradingRoot "logs/$Product.stderr.log") -PassThru
$process.Id | Set-Content (Join-Path $TradingRoot "logs/$Product.pid")
Write-Output "$Product worker launched on $ProductPort"
