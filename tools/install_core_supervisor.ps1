param(
    [string]$TaskName = 'Triad Core Supervisor',
    [int]$IntervalMinutes = 5
)
$ErrorActionPreference = 'Stop'
if ($IntervalMinutes -lt 1) { throw 'IntervalMinutes must be at least 1' }

$TriadRoot = Split-Path $PSScriptRoot -Parent
$EnsureScript = Join-Path $PSScriptRoot 'ensure_core.ps1'
if (!(Test-Path $EnsureScript)) { throw "Missing $EnsureScript" }

$PowerShell = (Get-Command powershell.exe -ErrorAction Stop).Source
$Arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + $EnsureScript + '"'
$Action = New-ScheduledTaskAction -Execute $PowerShell -Argument $Arguments -WorkingDirectory $TriadRoot
$AtLogon = New-ScheduledTaskTrigger -AtLogOn
$Periodic = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) -RepetitionDuration ([TimeSpan]::MaxValue)
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger @($AtLogon, $Periodic) -Settings $Settings -Description 'Ensures Triad Core is running; Core owns downstream service health.' -Force | Out-Null

Write-Output "Installed '$TaskName'. Core will be checked at logon and every $IntervalMinutes minute(s)."
