param(
    [string]$TaskName = 'Triad Core Supervisor',
    [ValidateRange(1, 1440)][int]$IntervalMinutes = 5,
    [switch]$ValidateOnly
)
$ErrorActionPreference = 'Stop'
if ($IntervalMinutes -lt 1) { throw 'IntervalMinutes must be at least 1' }

$TriadRoot = Split-Path $PSScriptRoot -Parent
$EnsureScript = Join-Path $PSScriptRoot 'ensure_core.ps1'
if (!(Test-Path $EnsureScript)) { throw "Missing $EnsureScript" }

$PowerShell = (Get-Command powershell.exe -ErrorAction Stop).Source
$Arguments = '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $EnsureScript + '"'
$Action = New-ScheduledTaskAction -Execute $PowerShell -Argument $Arguments -WorkingDirectory $TriadRoot
$UserId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$AtLogon = New-ScheduledTaskTrigger -AtLogOn -User $UserId
# Omit duration for indefinite repetition. TimeSpan.MaxValue produces an invalid
# Windows Task Scheduler duration on some installations.
$Periodic = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$Principal = New-ScheduledTaskPrincipal -UserId $UserId -LogonType Interactive -RunLevel Limited
$Task = New-ScheduledTask -Action $Action -Trigger @($AtLogon, $Periodic) -Settings $Settings `
    -Principal $Principal -Description 'Checks Core and its local Ollama dependency without inference, model downloads or trading.'

if ($ValidateOnly) {
    [ordered]@{
        Principal = [ordered]@{UserId=$Principal.UserId; LogonType=[int]$Principal.LogonType; RunLevel=[int]$Principal.RunLevel}
        Actions = @([ordered]@{Execute=$Action.Execute; Arguments=$Action.Arguments; WorkingDirectory=$Action.WorkingDirectory})
        Settings = [ordered]@{MultipleInstances=[int]$Settings.MultipleInstances; RestartCount=$Settings.RestartCount; RestartInterval=$Settings.RestartInterval; StartWhenAvailable=$Settings.StartWhenAvailable}
        Triggers = @(
            [ordered]@{Type='Logon'; UserId=$AtLogon.UserId; Enabled=$AtLogon.Enabled},
            [ordered]@{Type='Periodic'; StartBoundary=$Periodic.StartBoundary; Repetition=[ordered]@{Interval=$Periodic.Repetition.Interval; Duration=$Periodic.Repetition.Duration}}
        )
        Registered = $false
    } | ConvertTo-Json -Depth 5
    exit 0
}
Register-ScheduledTask -TaskName $TaskName -InputObject $Task -Force | Out-Null

Write-Output "Installed '$TaskName'. Core will be checked at logon and every $IntervalMinutes minute(s)."
