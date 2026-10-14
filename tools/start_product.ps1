# Launch a product worker on its own interpreter (Mission 7 spec §3.2): Triad on .venv-triad,
# Aegis on .venv-aegis. One Core codebase; only the dependencies differ. The supervisor
# (tools/ensure_product_worker.py) and Core's trusted restart both come through here.
[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet('triad','aegis')][string]$Product,
    [switch]$OnlyIfStopped,
    [string]$EnvironmentRoot = ''
)
$ErrorActionPreference = 'Stop'
$TradingRoot = Split-Path $PSScriptRoot -Parent
$EnvRoot = if ($EnvironmentRoot) { $EnvironmentRoot } else { $TradingRoot }
$TradingPython = Join-Path $EnvRoot ".venv-$Product/Scripts/python.exe"
if (!(Test-Path -LiteralPath $TradingPython)) {
    # Before any listener is touched: a missing environment never stops the running worker.
    throw "Missing ${TradingPython}: run tools/bootstrap.ps1 -Product $Product"
}
$ProductPort = if ($Product -eq 'triad') {8101} else {8102}
$ProductApp = "products.$Product.server:app"
$listeners = Get-NetTCPConnection -LocalPort $ProductPort -State Listen -ErrorAction SilentlyContinue
if ($OnlyIfStopped -and $listeners) {
    Write-Output "$Product port is occupied; supervisor will not stop its owner"
    exit 0
}
if ($OnlyIfStopped) {
    $stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffffffZ')
    foreach ($stream in @('stdout', 'stderr')) {
        $previous = Join-Path $TradingRoot "logs/$Product.$stream.log"
        if (Test-Path -LiteralPath $previous) {
            Copy-Item -LiteralPath $previous -Destination (Join-Path $TradingRoot "logs/$Product-before-recovery-$stamp.$stream.log")
        }
    }
}
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
