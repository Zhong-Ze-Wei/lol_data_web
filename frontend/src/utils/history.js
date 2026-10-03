export function stateCount(states, key) {
  return states ? (states[key] ?? 0) : undefined;
}

export function historyLabel(progress) {
  if (
    progress.last_run?.status === "running" ||
    progress.worker?.status === "continue"
  )
    return "正在补采";
  if (progress.complete_available) return "当前可用战报已补齐";
  if (progress.snapshot_completed) return "当前补采已审计，仍有待发布或源缺项";
  if (progress.worker?.status === "failed") return "补采遇到失败任务";
  if (progress.has_runnable_work) return "存在可继续补采的任务";
  if (progress.next_retry_at) return "等待下一次重试";
  if (progress.discovery_complete) return "目录发现完成，继续核验战报";
  return progress.last_run ? "正在建立历史赛事清单" : "等待首次历史补采";
}
