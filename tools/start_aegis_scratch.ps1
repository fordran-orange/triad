# Start or stop a scratch Aegis worker: this checkout's code on a scratch store (Optimization Lab
# v2, Phase 2). Browser evidence and benchmarks come from it, never from the product worker or
# the product store. The product ports and any port already listening are refused before
# anything touches disk.
#
#   tools/start_aegis_scratch.ps1 -Port 8103 -DataRoot C:\Triad\data\temp\lab-scratch
#   tools/start_aegis_scratch.ps1 -Stop [-PidFile logs\aegis-scratch.pid]
#
# -Stop ends only the process whose id this script wrote to -PidFile, and only while that process
# is still a uvicorn Aegis worker on a scratch port; anything else prints "nothing to stop". The
# environment variables are set here, not by the caller: a WMI launch does not inherit a shell.
[CmdletBinding()]
param(
    [int]$Port = 8103,
    [string]$DataRoot = '',
    [string]$EnvironmentRoot = 'C:\Triad',
    [string]$ArchiveRoot = 'C:\Triad',
    [string]$PidFile = 'logs\aegis-scratch.pid',
    [int]$Workers = 4,
    [switch]$Stop
)
$ErrorActionPreference = 'Stop'
$Root = Split-Path $PSScriptRoot -Parent
if (![IO.Path]::IsPathRooted($PidFile)) { $PidFile = Join-Path $Root $PidFile }
$App = 'products.aegis.server:app'

function Assert-ScratchPort {
    if ($Port -in @(8101, 8102)) {
        throw "refused: port $Port is a product port"
    }
}

function Get-NormalPath([string]$Path) {
    [IO.Path]::GetFullPath($Path).TrimEnd('\')
}

if ($Stop) {
    if (!(Test-Path -LiteralPath $PidFile)) {
        Write-Output 'nothing to stop'
        exit 0
    }
    $WorkerPid = [int](Get-Content -LiteralPath $PidFile -Raw).Trim()
    $Worker = Get-CimInstance Win32_Process -Filter "ProcessId = $WorkerPid"
    $Running = $Worker -and $Worker.CommandLine -match "uvicorn $([regex]::Escape($App)) .*--port (\d+)"
    if (!$Running) {
        Write-Output 'nothing to stop'
        exit 0
    }
    $Port = [int]$Matches[1]
    Assert-ScratchPort  # a pid file that names a product worker is refused, never obeyed
    # The venv's python.exe is a launcher stub; its child is the listener and exits with it.
    $Family = @($WorkerPid) + @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $WorkerPid" | ForEach-Object { $_.ProcessId })
    Stop-Process -Id $WorkerPid
    $Deadline = (Get-Date).AddSeconds(30)
    while ((Get-Process -Id $Family -ErrorAction SilentlyContinue) -and (Get-Date) -lt $Deadline) {
        Start-Sleep -Milliseconds 200
    }
    if (Get-Process -Id $Family -ErrorAction SilentlyContinue) {
        throw "the scratch worker $WorkerPid (port $Port) did not exit within 30 s"
    }
    Remove-Item -LiteralPath $PidFile
    Write-Output "scratch worker $WorkerPid stopped (port $Port)"
    exit 0
}

# Refusals first: nothing below runs for a product port or a port someone already listens on.
Assert-ScratchPort
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    throw "refused: port $Port is already listening"
}
if (!$DataRoot) {
    throw "refused: -DataRoot is required to start"
}
$Python = Join-Path $EnvironmentRoot '.venv-aegis\Scripts\python.exe'
if (!(Test-Path -LiteralPath $Python)) {
    throw "Missing ${Python}: run tools/bootstrap.ps1 -Product aegis"
}
if (![IO.Path]::IsPathRooted($DataRoot)) { $DataRoot = Join-Path $Root $DataRoot }
$DataRoot = Get-NormalPath $DataRoot

# The raw archives: a checkout without them links the archive root's folder (gitignored under
# data/raw/*). Pinned relative paths are identical on both roots, so pins stay portable.
$Archives = Join-Path $Root 'data\raw\HFDataLibrary'
if (!(Test-Path -LiteralPath $Archives)) {
    $Source = Join-Path $ArchiveRoot 'data\raw\HFDataLibrary'
    if (!(Test-Path -LiteralPath $Source)) {
        throw "Missing ${Source}: no raw archives to link"
    }
    New-Item -ItemType Directory -Force -Path (Split-Path $Archives -Parent) | Out-Null
    New-Item -ItemType Junction -Path $Archives -Target $Source | Out-Null
}
New-Item -ItemType Directory -Force -Path $DataRoot, (Join-Path $Root 'logs'), (Split-Path $PidFile -Parent) | Out-Null

$env:PYTHONPATH = "$Root\app"
$env:AEGIS_DATA_ROOT = $DataRoot
$env:AEGIS_POOL_WORKERS = $Workers
$Process = Start-Process -FilePath $Python -ArgumentList '-m', 'uvicorn', $App, '--host', '127.0.0.1', '--port', "$Port" -WorkingDirectory $Root -WindowStyle Hidden -RedirectStandardOutput (Join-Path $Root 'logs\aegis-scratch.stdout.log') -RedirectStandardError (Join-Path $Root 'logs\aegis-scratch.stderr.log') -PassThru
$Process.Id | Set-Content -LiteralPath $PidFile

# A closed loopback port refuses only after about 2 s on this machine: 3 s per request.
$AppRoot = Get-NormalPath "$Root\app"
$Deadline = (Get-Date).AddSeconds(60)
$Last = 'no answer yet'
while ((Get-Date) -lt $Deadline) {
    if ($Process.HasExited) {
        throw "the scratch worker exited with code $($Process.ExitCode): see logs\aegis-scratch.stderr.log"
    }
    try {
        $Health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health/live" -TimeoutSec 3
    } catch {
        $Last = $_.Exception.Message
        Start-Sleep -Milliseconds 500
        continue
    }
    $ServedApp = if ($Health.app_root) { Get-NormalPath $Health.app_root } else { '' }
    $ServedData = if ($Health.data_root) { Get-NormalPath $Health.data_root } else { '' }
    if ($ServedApp -ieq $AppRoot -and $ServedData -ieq $DataRoot) {
        Write-Output "scratch worker $($Process.Id) on port $Port serves $AppRoot on $DataRoot (pid file $PidFile)"
        exit 0
    }
    throw "the worker on port $Port serves app_root '$($Health.app_root)' and data_root '$($Health.data_root)', expected '$AppRoot' and '$DataRoot'; stop it with -Stop -PidFile $PidFile"
}
throw "the scratch worker did not answer /health/live within 60 s ($Last): see logs\aegis-scratch.stderr.log"
