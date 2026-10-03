param([string]$At = '08:25')
$ErrorActionPreference = 'Stop'
if ($At -notmatch '^([01]\d|2[0-3]):[0-5]\d$') { throw '时间必须为 HH:mm' }
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimePath = Join-Path $projectRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $runtimePath)) { throw '请先创建项目 .venv 并安装依赖' }
$scriptPath = Join-Path $PSScriptRoot 'run-history.ps1'
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $scriptPath + '"') -WorkingDirectory $projectRoot
$triggers = @((New-ScheduledTaskTrigger -Daily -At $At), (New-ScheduledTaskTrigger -AtLogOn -User ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name)))
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -RunOnlyIfNetworkAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName 'LOL Data History Backfill' -Action $action -Trigger $triggers -Settings $settings -Principal $principal -Description 'Resume bounded historical ScoreGG batches; yields to daily sync' -Force | Out-Null
$metadata = @{enabled=$true;mode='windows';time=$At;timezone='Asia/Hong_Kong';task_name='LOL Data History Backfill';resume_on_logon=$true}
$metadata | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $projectRoot 'data/history-schedule.json') -Encoding utf8
Get-ScheduledTaskInfo -TaskName 'LOL Data History Backfill' | Select-Object NextRunTime,LastRunTime,LastTaskResult
