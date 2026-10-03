import { afterEach, describe, expect, it, vi } from "vitest";
import { createApp, nextTick } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import App from "../src/App.vue";
import { syncFeedback } from "../src/utils/history.js";

let app;
afterEach(() => {
  app?.unmount();
  app = null;
  document.body.innerHTML = "";
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function liveStatus(changes = {}) {
  return {
    last_run: {
      command: "history",
      status: "running",
      started_at: "2020-01-01T00:00:00Z",
      failed: 0,
    },
    history_worker: {
      status: "running",
      alive: true,
      heartbeat_state: "fresh",
      heartbeat_age_seconds: 0,
      heartbeat_timeout_seconds: 90,
      current_batch: 38,
      last_completed_batch: 37,
    },
    tasks: {},
    legacy_matches: 10,
    verified_matches: 20,
    data_range: { min_date: "2016-01-01", max_date: "2016-12-31" },
    ...changes,
  };
}

async function showStatus(status, fetch) {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-10-03T21:40:24Z"));
  vi.stubGlobal(
    "fetch",
    fetch ||
      vi.fn(async () => new Response(JSON.stringify(status), { status: 200 })),
  );
  const router = createRouter({
    history: createMemoryHistory(),
    routes: ["/", "/match", "/player", "/team", "/hero", "/analytics"].map(
      (path) => ({ path, component: { render: () => null } }),
    ),
  });
  await router.push("/");
  await router.isReady();
  const element = document.createElement("div");
  document.body.append(element);
  app = createApp(App);
  app.use(router);
  app.mount(element);
  await vi.advanceTimersByTimeAsync(0);
  await nextTick();
}

describe("全局采集状态反馈", () => {
  it("只有近期运行心跳才显示历史补采进行中，时间表示本次状态读取", async () => {
    await showStatus(liveStatus());
    expect(document.querySelector(".sync-inner").textContent).toContain(
      "历史补采进行中",
    );
    expect(document.querySelector(".sync-indicator.running")).not.toBeNull();
    expect(document.querySelector(".sync-time").textContent).toContain(
      "采集状态更新 2026-10-04 05:40:24",
    );
    expect(document.body.textContent).not.toContain("最近采集未完成");
    expect(document.querySelector(".sync-time").textContent).not.toContain(
      "2020-01-01",
    );
  });

  it.each([
    ["daily_pause", "历史补采等待每日采集窗口结束"],
    ["locked", "历史补采等待其他采集任务结束"],
    ["retry_later", "历史补采等待重试"],
    ["retry_wait", "历史补采等待重试"],
  ])("%s有近期心跳但明确显示等待，不显示采集进行中", async (phase, label) => {
    const status = liveStatus();
    status.history_worker.status = phase;
    await showStatus(status);
    expect(document.querySelector(".sync-inner").textContent).toContain(label);
    expect(document.querySelector(".sync-indicator.running")).toBeNull();
    expect(document.body.textContent).not.toContain("历史补采进行中");
  });

  it.each([
    null,
    { alive: false, status: "continue", heartbeat_state: "expired" },
    { alive: false, status: "running", heartbeat_state: "future" },
    { alive: false, heartbeat_state: "missing" },
  ])("旧running记录与无效心跳不推断后台正在运行：%j", async (worker) => {
    await showStatus(liveStatus({ history_worker: worker }));
    expect(document.querySelector(".sync-inner").textContent).toContain(
      "采集状态待确认",
    );
    expect(document.querySelector(".sync-indicator.running")).toBeNull();
  });

  it("正常预算用尽后已有下一批运行，不显示异常或全部完成", async () => {
    const status = liveStatus();
    status.last_run.status = "budget_exhausted";
    await showStatus(status);
    expect(document.body.textContent).toContain("历史补采进行中");
    expect(document.querySelector(".sync-indicator.failed")).toBeNull();
    expect(document.body.textContent).not.toContain("全部完成");
    expect(document.body.textContent).not.toContain("未完成");
  });

  it("预算退出但没有活跃后台只表示本批结束、后续待补采", async () => {
    const status = liveStatus({ history_worker: null });
    status.last_run.status = "budget_exhausted";
    await showStatus(status);
    expect(document.body.textContent).toContain("本批已结束，后续待补采");
    expect(document.querySelector(".sync-indicator.running")).toBeNull();
    expect(document.querySelector(".sync-indicator.failed")).toBeNull();
  });

  it.each([false, true])(
    "发现分配预算受限产生partial不误报失败，后台存活为%s",
    async (alive) => {
      const status = liveStatus({
        history_worker: alive ? liveStatus().history_worker : null,
      });
      status.last_run.status = "partial";
      status.last_run.details = {
        discovery_limited: true,
        discovery_errors: [],
      };
      await showStatus(status);
      expect(document.body.textContent).toContain(
        alive ? "历史补采进行中" : "本批发现预算已用尽，后续待补采",
      );
      expect(document.querySelector(".sync-indicator.failed")).toBeNull();
      expect(document.body.textContent).not.toContain("失败待核查");
    },
  );

  it.each(["partial", "budget_exhausted"])(
    "%s即使达到预算也不掩盖实际发现错误",
    async (phase) => {
      const status = liveStatus();
      status.last_run.status = phase;
      status.last_run.details = {
        discovery_limited: true,
        discovery_errors: [{ tournament_id: 344, error: "源响应无法读取" }],
      };
      await showStatus(status);
      expect(document.body.textContent).toContain("有失败待核查");
      expect(document.querySelector(".sync-indicator.failed")).not.toBeNull();
    },
  );

  it.each(["failed", "partial"])(
    "后台仍在补采时不掩盖上一批%s",
    async (phase) => {
      const status = liveStatus();
      status.last_run.status = phase;
      await showStatus(status);
      expect(document.body.textContent).toContain("有失败待核查");
      expect(document.querySelector(".sync-indicator.failed")).not.toBeNull();
      expect(document.querySelector(".sync-indicator.running")).toBeNull();
    },
  );

  it("明确失败任务仍显示失败提示，即使本批预算正常结束", async () => {
    const status = liveStatus({ tasks: { failed: 2 } });
    status.last_run.status = "budget_exhausted";
    await showStatus(status);
    expect(document.body.textContent).toContain("有失败待核查");
    expect(document.querySelector(".sync-indicator.failed")).not.toBeNull();
  });

  it("30秒只读刷新不中断已有反馈，并在下一次成功后更新状态", async () => {
    const first = liveStatus();
    let finishRefresh;
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify(first), { status: 200 }),
      )
      .mockImplementationOnce(
        () => new Promise((resolve) => (finishRefresh = resolve)),
      );
    await showStatus(first, fetch);
    await vi.advanceTimersByTimeAsync(30000);
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(document.body.textContent).toContain("历史补采进行中");
    expect(document.body.textContent).not.toContain("读取采集状态");
    const updated = liveStatus();
    updated.history_worker.status = "daily_pause";
    finishRefresh(new Response(JSON.stringify(updated), { status: 200 }));
    await vi.advanceTimersByTimeAsync(0);
    expect(document.body.textContent).toContain("历史补采等待每日采集窗口结束");
    expect(document.querySelector(".sync-time").textContent).toContain(
      "05:40:54",
    );
    expect(
      fetch.mock.calls.every(
        ([url, options]) =>
          url === "/api/sync/status" && options.method === "GET",
      ),
    ).toBe(true);
  });

  it("状态刷新卡住时本地心跳仍过期，避免并发轮询，卸载取消请求和计时器", async () => {
    const status = liveStatus();
    status.history_worker.heartbeat_age_seconds = 80;
    let pendingSignal;
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify(status), { status: 200 }),
      )
      .mockImplementationOnce((url, options) => {
        pendingSignal = options.signal;
        return new Promise(() => {});
      });
    await showStatus(status, fetch);
    expect(document.querySelector(".sync-indicator.running")).not.toBeNull();
    await vi.advanceTimersByTimeAsync(15000);
    expect(document.querySelector(".sync-indicator.running")).toBeNull();
    expect(document.body.textContent).toContain("采集状态待确认");
    await vi.advanceTimersByTimeAsync(90000);
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(document.querySelector(".sync-time").textContent).toContain(
      "05:40:24",
    );
    app.unmount();
    app = null;
    expect(pendingSignal.aborted).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
    await vi.advanceTimersByTimeAsync(60000);
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("刷新失败停止运行标记，保留上一成功状态读取时间与数据范围", async () => {
    const status = liveStatus();
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify(status), { status: 200 }),
      )
      .mockRejectedValueOnce(new Error("状态连接中断"));
    await showStatus(status, fetch);
    await vi.advanceTimersByTimeAsync(30000);
    expect(document.body.textContent).toContain("采集状态暂不可用");
    expect(document.querySelector(".sync-indicator.running")).toBeNull();
    expect(document.querySelector(".sync-indicator.failed")).not.toBeNull();
    expect(document.querySelector(".sync-time").textContent).toContain(
      "05:40:24",
    );
    expect(document.body.textContent).toContain("2016-01-01 至 2016-12-31");
    expect(document.querySelector(".site-footer").textContent).toContain(
      "已核验 20 场",
    );
  });

  it("失败后的下一次请求挂起时仍显示不可用，只有新成功响应才恢复运行标记", async () => {
    const status = liveStatus();
    let finishRefresh;
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify(status), { status: 200 }),
      )
      .mockRejectedValueOnce(new Error("状态连接中断"))
      .mockImplementationOnce(
        () => new Promise((resolve) => (finishRefresh = resolve)),
      );
    await showStatus(status, fetch);
    await vi.advanceTimersByTimeAsync(30000);
    expect(document.body.textContent).toContain("采集状态暂不可用");
    await vi.advanceTimersByTimeAsync(30000);
    expect(fetch).toHaveBeenCalledTimes(3);
    expect(document.body.textContent).toContain("采集状态暂不可用");
    expect(document.querySelector(".sync-indicator.running")).toBeNull();
    expect(document.querySelector(".sync-indicator.failed")).not.toBeNull();
    expect(document.querySelector(".sync-time").textContent).toContain(
      "05:40:24",
    );
    finishRefresh(new Response(JSON.stringify(status), { status: 200 }));
    await vi.advanceTimersByTimeAsync(0);
    expect(document.body.textContent).toContain("历史补采进行中");
    expect(document.querySelector(".sync-indicator.running")).not.toBeNull();
    expect(document.querySelector(".sync-indicator.failed")).toBeNull();
    expect(document.querySelector(".sync-time").textContent).toContain(
      "05:41:24",
    );
  });

  it("已生成的fresh响应延迟120秒才送达，不会重新获得90秒运行标记", async () => {
    const status = liveStatus();
    let deliverResponse;
    const fetch = vi.fn(
      () => new Promise((resolve) => (deliverResponse = resolve)),
    );
    await showStatus(status, fetch);
    await vi.advanceTimersByTimeAsync(120000);
    expect(fetch).toHaveBeenCalledTimes(1);
    deliverResponse(new Response(JSON.stringify(status), { status: 200 }));
    await vi.advanceTimersByTimeAsync(0);
    expect(document.body.textContent).toContain("采集状态待确认");
    expect(document.querySelector(".sync-indicator.running")).toBeNull();
    expect(document.querySelector(".sync-time").textContent).toContain(
      "05:42:24",
    );
  });

  it.each([
    ["success", null, "最近一批采集已完成"],
    ["completed", { status: "completed", alive: false }, "最近一批采集已完成"],
    ["running", { status: "failed", alive: false }, "历史补采遇到错误"],
    [
      "budget_exhausted",
      { status: "stopped", alive: false },
      "历史补采已停止，后续待补采",
    ],
  ])("%s只描述本批或后台终态，不宣称全历史完成", (status, worker, label) => {
    const feedback = syncFeedback({
      last_run: { status, command: "history" },
      history_worker: worker,
    });
    expect(feedback.label).toBe(label);
    expect(feedback.running).toBe(false);
    expect(feedback.label).not.toContain("全部");
    if (worker?.status === "failed") expect(feedback.failed).toBe(true);
  });
});
