param([string]$At = '08:00')
$ErrorActionPreference = 'Stop'
if ($At -notmatch '^([01]\d|2[0-3]):[0-5]\d$') { throw '时间必须为 HH:mm' }
$projectRoot = Split-Path -Parent $PSScriptRoot
$scriptPath = Join-Path $PSScriptRoot 'run-daily.ps1'
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $scriptPath + '"') -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 20) -RunOnlyIfNetworkAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName 'LOL Data Daily Sync' -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description 'Daily ScoreGG discovery and idempotent LOL data import' -Force | Out-Null
$metadata = @{enabled=$true;mode='windows';time=$At;timezone='Asia/Hong_Kong';task_name='LOL Data Daily Sync'}
$metadata | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $projectRoot 'data/schedule.json') -Encoding utf8
Get-ScheduledTaskInfo -TaskName 'LOL Data Daily Sync' | Select-Object NextRunTime,LastRunTime,LastTaskResult
