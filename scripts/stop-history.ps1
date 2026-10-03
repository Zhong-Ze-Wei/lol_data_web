param([switch]$Preview)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).ProviderPath
$runtimePath = (Resolve-Path -LiteralPath (Join-Path $projectRoot '.venv/Scripts/python.exe')).ProviderPath
$taskName = 'LOL Data History Backfill'

# 只接受项目解释器的实际启动形式，不匹配 run.py、daily 或命令中的字符串。
$escapedRuntime = [regex]::Escape($runtimePath)
$rootPattern = '^\s*(?i:"' + $escapedRuntime + '"|' + $escapedRuntime + ')\s+(?:-X\s+utf8\s+)?-m\s+(?:scripts\.history_worker(?:\s|$)|scripts\.pipeline\s+history(?:\s|$))'
$snapshot = @(Get-CimInstance Win32_Process)
$roots = @($snapshot | Where-Object {
    $_.ExecutablePath -ieq $runtimePath -and [regex]::IsMatch([string]$_.CommandLine, $rootPattern)
})
$selected = @{}
foreach ($process in $roots) { $selected[[int]$process.ProcessId] = $process }

# PPID可能指向已复用的父PID；创建时间早于当前父进程的旧孤儿不能算后代。
do {
    $added = $false
    foreach ($process in $snapshot) {
        $processId = [int]$process.ProcessId
        $parentId = [int]$process.ParentProcessId
        if ($selected.ContainsKey($processId) -or -not $selected.ContainsKey($parentId)) { continue }
        $parent = $selected[$parentId]
        if ($null -eq $process.CreationDate -or $null -eq $parent.CreationDate) {
            throw '无法核对后代创建时间，拒绝生成停止计划'
        }
        if ($process.CreationDate -lt $parent.CreationDate) { continue }
        $selected[$processId] = $process
        $added = $true
    }
} while ($added)

# pipeline也可能被选为根；按完整祖先链排序，仍先停worker再停其孙级进程。
$plan = @(
    foreach ($process in $selected.Values) {
        if ($null -eq $process.CreationDate -or -not $process.ExecutablePath -or -not $process.CommandLine) {
            throw "无法完整核对PID $($process.ProcessId)，拒绝生成停止计划"
        }
        $depth = 0
        $ancestor = $process
        $seen = @{}
        while ($selected.ContainsKey([int]$ancestor.ParentProcessId)) {
            if ($seen.ContainsKey([int]$ancestor.ProcessId)) { throw '快照祖先链存在循环，拒绝停止' }
            $seen[[int]$ancestor.ProcessId] = $true
            $parent = $selected[[int]$ancestor.ParentProcessId]
            if ($ancestor.CreationDate -lt $parent.CreationDate) { break }
            $ancestor = $parent
            $depth++
        }
        [pscustomobject]@{
            Depth = $depth
            ProcessId = [int]$process.ProcessId
            ParentProcessId = [int]$process.ParentProcessId
            ExecutablePath = $process.ExecutablePath
            CommandLine = $process.CommandLine
            CreationDate = $process.CreationDate
        }
    }
) | Sort-Object Depth, @{Expression = { if ($_.CommandLine -cmatch '-m\s+scripts\.history_worker(?:\s|$)') { 0 } else { 1 } }}, ProcessId

if ($Preview) {
    Write-Host "仅预览：命名任务 $taskName 与以下项目历史采集进程将被停止；未执行任何停止操作。"
    $plan
    return
}

Stop-ScheduledTask -TaskName $taskName -TaskPath '\'
foreach ($process in $plan) {
    $current = Get-CimInstance Win32_Process -Filter "ProcessId = $($process.ProcessId)"
    if ($null -eq $current) { continue }
    if ($current.CreationDate -ne $process.CreationDate -or
        $current.ExecutablePath -cne $process.ExecutablePath -or
        $current.CommandLine -cne $process.CommandLine -or
        $current.ParentProcessId -ne $process.ParentProcessId) {
        throw "PID $($process.ProcessId)身份已变化，拒绝停止"
    }
    try {
        Stop-Process -Id $process.ProcessId
    } catch {
        # 停父wrapper可能让base自行退出；仅确认已消失时继续处理其余计划。
        $afterFailure = Get-CimInstance Win32_Process -Filter "ProcessId = $($process.ProcessId)"
        if ($null -eq $afterFailure) { continue }
        throw
    }
    Write-Host "已发送停止PID $($process.ProcessId)"
}

# 快照之后可能新生pipeline或base；只报告残留，不停止尚未逐个核对的对象。
$finalSnapshot = @(Get-CimInstance Win32_Process)
$remaining = @{}
$residualParents = $selected.Clone()
foreach ($process in $finalSnapshot) {
    $processId = [int]$process.ProcessId
    $isRoot = $process.ExecutablePath -ieq $runtimePath -and [regex]::IsMatch([string]$process.CommandLine, $rootPattern)
    $captured = $selected[$processId]
    $isCaptured = $null -ne $captured -and $process.CreationDate -eq $captured.CreationDate
    if ($isRoot -or $isCaptured) {
        $remaining[$processId] = $process
        $residualParents[$processId] = $process
    }
}
do {
    $added = $false
    foreach ($process in $finalSnapshot) {
        $processId = [int]$process.ProcessId
        if ($remaining.ContainsKey($processId)) { continue }
        $parent = $residualParents[[int]$process.ParentProcessId]
        if ($null -eq $parent) { continue }
        if ($null -eq $process.CreationDate -or $null -eq $parent.CreationDate) {
            throw '无法核对残留后代创建时间，停止未完成'
        }
        if ($process.CreationDate -lt $parent.CreationDate) { continue }
        $remaining[$processId] = $process
        $residualParents[$processId] = $process
        $added = $true
    }
} while ($added)
if ($remaining.Count -gt 0) {
    $remainingIds = ($remaining.Keys | Sort-Object) -join ', '
    throw "仍有项目历史采集进程PID $remainingIds，停止未完成；请重新预览后再处理"
}
Write-Host '项目历史采集进程已停止，残留检查通过。'
