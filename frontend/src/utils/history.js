export function stateCount(states, key) {
  return states ? (states[key] ?? 0) : undefined;
}

export function historyLabel(progress) {
  if (progress.worker?.alive === true) {
    if (progress.worker.status === "daily_pause") return "已让出每日采集窗口";
    if (progress.worker.status === "locked") return "等待其他采集任务结束";
    if (["retry_later", "retry_wait"].includes(progress.worker.status))
      return "等待下一次重试";
    return "正在补采";
  }
  if (progress.has_runnable_work) return "存在可继续补采的任务";
  if (progress.complete_available) return "当前可用战报已补齐";
  if (progress.snapshot_completed) return "当前补采已审计，仍有待发布或源缺项";
  if (progress.worker?.status === "failed") return "补采遇到失败任务";
  if (progress.next_retry_at) return "等待下一次重试";
  if (progress.discovery_complete) return "目录发现完成，继续核验战报";
  return progress.last_run ? "历史赛事清单尚未完成" : "等待首次历史补采";
}
