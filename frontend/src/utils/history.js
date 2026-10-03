export function stateCount(states, key) {
  return states ? (states[key] ?? 0) : undefined;
}

export function historyWorkerAlive(worker, elapsedSeconds = 0) {
  if (
    worker?.alive !== true ||
    worker.heartbeat_state !== "fresh" ||
    !Number.isFinite(worker.heartbeat_age_seconds) ||
    !Number.isFinite(worker.heartbeat_timeout_seconds) ||
    !Number.isFinite(elapsedSeconds) ||
    worker.heartbeat_age_seconds < 0 ||
    elapsedSeconds < 0 ||
    worker.heartbeat_timeout_seconds <= 0
  )
    return false;
  const age = worker.heartbeat_age_seconds + elapsedSeconds;
  return age >= 0 && age <= worker.heartbeat_timeout_seconds;
}

export function syncFeedback(sync, elapsedSeconds = 0) {
  const run = sync?.last_run;
  const worker = sync?.history_worker;
  const discoveryErrors = run?.details?.discovery_errors;
  const discoveryBudgetLimited =
    run?.status === "partial" &&
    run.details?.discovery_limited === true &&
    Array.isArray(discoveryErrors) &&
    discoveryErrors.length === 0 &&
    run.failed === 0;
  const failed =
    run?.status === "failed" ||
    (run?.status === "partial" && !discoveryBudgetLimited) ||
    run?.failed > 0 ||
    discoveryErrors?.length > 0 ||
    sync?.tasks?.failed > 0 ||
    worker?.status === "failed";
  if (historyWorkerAlive(worker, elapsedSeconds)) {
    const waiting = {
      daily_pause: "历史补采等待每日采集窗口结束",
      locked: "历史补采等待其他采集任务结束",
      retry_later: "历史补采等待重试",
      retry_wait: "历史补采等待重试",
    };
    const label = waiting[worker.status] || "历史补采进行中";
    return {
      label: label + (failed ? "，有失败待核查" : ""),
      running: !waiting[worker.status],
      failed,
    };
  }
  const labels = {
    success: "最近一批采集已完成",
    completed: "最近一批采集已完成",
    running: "采集状态待确认",
    partial: "最近一批部分完成",
    failed: "最近一批采集失败",
    cancelled: "采集已停止",
    budget_exhausted: "本批已结束，后续待补采",
    interrupted: "采集已中断，等待恢复",
    waiting_retry: "采集等待重试",
    stale: "源站暂无近期赛程",
  };
  let label = run ? labels[run.status] || "采集状态待确认" : "等待首次采集";
  if (discoveryBudgetLimited) label = "本批发现预算已用尽，后续待补采";
  if (worker?.status === "failed") label = "历史补采遇到错误";
  else if (worker?.status === "stopped" && run?.command === "history")
    label = "历史补采已停止，后续待补采";
  if (failed && run?.status !== "failed" && worker?.status !== "failed")
    label += "，有失败待核查";
  return { label, running: false, failed };
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
