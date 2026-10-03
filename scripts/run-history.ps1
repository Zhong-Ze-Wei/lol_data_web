$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimePath = Join-Path $projectRoot '.venv/Scripts/python.exe'
$logDirectory = Join-Path $projectRoot 'logs'
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
Set-Location -LiteralPath $projectRoot
& $runtimePath -X utf8 -m scripts.history_worker *>> (Join-Path $logDirectory 'history-process.log')
exit $LASTEXITCODE
