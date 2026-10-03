import { afterEach, describe, expect, it, vi } from "vitest";
import { createApp, nextTick } from "vue";
import HistoryProgress from "../src/components/HistoryProgress.vue";

let app;
afterEach(() => {
  app?.unmount();
  document.body.innerHTML = "";
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

async function showProgress(worker, fetch) {
  vi.useFakeTimers();
  const progress = {
    has_runnable_work: true,
    last_run: { status: "running" },
    counts: {
      catalog: { total: 3 },
      series: { total: 5 },
      results: { verified: 2 },
    },
    worker: {
      heartbeat_age_seconds: 0,
      heartbeat_timeout_seconds: 90,
      ...worker,
    },
  };
  vi.stubGlobal(
    "fetch",
    fetch ||
      vi.fn(
        async () => new Response(JSON.stringify(progress), { status: 200 }),
      ),
  );
  const element = document.createElement("div");
  document.body.append(element);
  app = createApp(HistoryProgress);
  app.mount(element);
  await vi.advanceTimersByTimeAsync(0);
  await nextTick();
  return progress;
}

describe("历史后台运行展示", () => {
  it("新会话首批显示当前1而不是旧的完成2", async () => {
    await showProgress({
      status: "running",
      alive: true,
      batch: 0,
      current_batch: 1,
    });
    expect(document.querySelector(".history-state.active").textContent).toBe(
      "正在补采",
    );
    expect(document.body.textContent).toContain("当前第 1 批");
    expect(document.body.textContent).not.toContain("当前第 2 批");
  });
  it("旧continue与旧SyncRun只显示上次完成，不声称仍在运行", async () => {
    await showProgress({ status: "continue", alive: false, batch: 2 });
    expect(document.querySelector(".history-state.active")).toBeNull();
    expect(document.body.textContent).toContain("上次完成第 2 批");
    expect(document.body.textContent).toContain("运行状态待确认");
    expect(document.body.textContent).not.toContain("正在补采");
    expect(document.body.textContent).not.toContain("当前第");
  });
  it.each([
    ["daily_pause", "已让出每日采集窗口"],
    ["locked", "等待其他采集任务结束"],
    ["retry_later", "等待下一次重试"],
    ["retry_wait", "等待下一次重试"],
  ])("%s保持alive但明确等待", async (status, label) => {
    await showProgress({
      status,
      alive: true,
      current_batch: null,
      last_completed_batch: 1,
    });
    expect(document.querySelector(".history-state.active").textContent).toBe(
      label,
    );
    expect(document.body.textContent).not.toContain("正在补采");
    expect(document.body.textContent).toContain("上次完成第 1 批");
  });
  it.each([
    ["stopped", "后台执行已停止"],
    ["completed", "本轮后台执行已结束"],
  ])("%s不把历史快照当全量完成", async (status, label) => {
    await showProgress({ status, alive: false, last_completed_batch: 1 });
    expect(document.querySelector(".history-state.active")).toBeNull();
    expect(document.body.textContent).toContain(label);
    expect(document.body.textContent).not.toContain("全部");
  });
  it("页面缓存的近期心跳会按接收后的时间过期，刷新卡住也不永久显示正在补采", async () => {
    let first = true;
    let progress;
    const fetch = vi.fn(async () => {
      if (!first) return new Promise(() => {});
      first = false;
      return new Response(JSON.stringify(progress), { status: 200 });
    });
    progress = {
      has_runnable_work: true,
      worker: {
        status: "running",
        alive: true,
        current_batch: 1,
        heartbeat_age_seconds: 80,
        heartbeat_timeout_seconds: 90,
      },
    };
    await showProgress({}, fetch);
    expect(document.querySelector(".history-state.active")).not.toBeNull();
    await vi.advanceTimersByTimeAsync(15000);
    expect(document.querySelector(".history-state.active")).toBeNull();
    expect(document.body.textContent).not.toContain("正在补采");
    await vi.advanceTimersByTimeAsync(15000);
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(document.body.textContent).toContain("运行状态待确认");
    app.unmount();
    app = null;
    expect(vi.getTimerCount()).toBe(0);
  });
});
