$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot '.venv/Scripts/python.exe'
$logDirectory = Join-Path $projectRoot 'logs'
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$logFile = Join-Path $logDirectory ('daily-' + (Get-Date -Format 'yyyy-MM-dd') + '.log')
Set-Location -LiteralPath $projectRoot
& $python -m scripts.backup_database *>> $logFile
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $python -m scripts.pipeline daily --max-requests 400 --max-seconds 900 *>> $logFile
exit $LASTEXITCODE
