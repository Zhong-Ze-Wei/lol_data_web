import { afterEach, describe, expect, it, vi } from "vitest";
import { createApp, nextTick } from "vue";
import HistoryProgress from "../src/components/HistoryProgress.vue";

let app;
afterEach(() => {
  app?.unmount();
  app = null;
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
      heartbeat_state: "fresh",
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
  it.each([
    [
      { total: 388, discovered: 219, queued: 167, running: 1, failed: 1 },
      "219/388项",
    ],
    [{ total: 0, discovered: 0 }, "0/0项"],
    [{ total: 3, queued: 2, failed: 1 }, "0/3项"],
    [undefined, "—/—项"],
  ])(
    "目录进度按已读取阶段列表的数量显示，不把其他状态算入分子",
    async (catalog, expected) => {
      const fetch = vi.fn(
        async () =>
          new Response(JSON.stringify({ counts: { catalog } }), {
            status: 200,
          }),
      );
      await showProgress({}, fetch);
      const metric = document.querySelector(".history-metrics > div");
      expect(metric.querySelector("dt").textContent).toBe("目录进度");
      expect(metric.querySelector("dd").textContent.replace(/\s/g, "")).toBe(
        expected,
      );
      expect(metric.title).toBe(
        "已读取赛事阶段列表的目录项数 / 来源目录总数，阶段赛程与战报仍需另采",
      );
      expect(metric.textContent).not.toContain("完成");
    },
  );

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
        heartbeat_state: "fresh",
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

  it.each([
    [20000, 80],
    [120000, 0],
  ])(
    "已生成的fresh响应延迟%s毫秒送达时计入请求耗时，不重获有效期",
    async (delay, age) => {
      let deliverResponse;
      const fetch = vi.fn(
        () => new Promise((resolve) => (deliverResponse = resolve)),
      );
      const progress = await showProgress(
        { status: "running", alive: true, heartbeat_age_seconds: age },
        fetch,
      );
      await vi.advanceTimersByTimeAsync(delay);
      deliverResponse(new Response(JSON.stringify(progress), { status: 200 }));
      await vi.advanceTimersByTimeAsync(0);
      expect(document.querySelector(".history-state.active")).toBeNull();
      expect(document.body.textContent).not.toContain("正在补采");
      expect(document.body.textContent).toContain("运行状态待确认");
      expect(fetch).toHaveBeenCalledTimes(1);
    },
  );

  it("刷新超过30秒仍挂起时不并发或取消请求，也不延长缓存心跳", async () => {
    let pendingSignal;
    let progress;
    const fetch = vi
      .fn()
      .mockImplementationOnce(
        async () => new Response(JSON.stringify(progress), { status: 200 }),
      )
      .mockImplementationOnce((url, options) => {
        pendingSignal = options.signal;
        return new Promise(() => {});
      });
    progress = {
      has_runnable_work: true,
      worker: {
        status: "running",
        alive: true,
        heartbeat_state: "fresh",
        heartbeat_age_seconds: 0,
        heartbeat_timeout_seconds: 90,
      },
    };
    await showProgress({}, fetch);
    await vi.advanceTimersByTimeAsync(105000);
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(pendingSignal.aborted).toBe(false);
    expect(document.querySelector(".history-state.active")).toBeNull();
    expect(document.body.textContent).toContain("运行状态待确认");
    expect(document.body.textContent).not.toContain("正在补采");
    expect(fetch.mock.calls.every(([url]) => url === "/api/sync/history")).toBe(
      true,
    );
    app.unmount();
    app = null;
    expect(pendingSignal.aborted).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
    await vi.advanceTimersByTimeAsync(60000);
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("失败后下一请求挂起仍显示不可用，保留覆盖统计直到成功恢复", async () => {
    let deliverRefresh;
    let progress;
    const fetch = vi
      .fn()
      .mockImplementationOnce(
        async () => new Response(JSON.stringify(progress), { status: 200 }),
      )
      .mockRejectedValueOnce(new Error("进度连接中断"))
      .mockImplementationOnce(
        () => new Promise((resolve) => (deliverRefresh = resolve)),
      );
    progress = {
      has_runnable_work: true,
      counts: { catalog: { total: 3, discovered: 1 }, series: { total: 5 } },
      worker: {
        status: "running",
        alive: true,
        heartbeat_state: "fresh",
        heartbeat_age_seconds: 0,
        heartbeat_timeout_seconds: 90,
        current_batch: 38,
      },
    };
    await showProgress({}, fetch);
    expect(
      document
        .querySelector(".history-metrics dd")
        .textContent.replace(/\s/g, ""),
    ).toBe("1/3项");
    await vi.advanceTimersByTimeAsync(30000);
    expect(document.querySelector(".history-state").textContent).toBe(
      "历史补采进度暂不可用",
    );
    expect(document.querySelector(".history-state.active")).toBeNull();
    await vi.advanceTimersByTimeAsync(30000);
    expect(fetch).toHaveBeenCalledTimes(3);
    expect(document.querySelector(".history-state").textContent).toBe(
      "历史补采进度暂不可用",
    );
    expect(document.querySelector(".history-state.active")).toBeNull();
    expect(document.body.textContent).not.toContain("正在补采");
    expect(document.body.textContent).not.toContain("后台最近心跳正常");
    expect(document.body.textContent).not.toContain("当前第 38 批");
    expect(
      document
        .querySelector(".history-metrics dd")
        .textContent.replace(/\s/g, ""),
    ).toBe("1/3项");
    deliverRefresh(
      new Response(
        JSON.stringify({
          ...progress,
          counts: {
            catalog: { total: 4, discovered: 2 },
            series: { total: 6 },
          },
        }),
        { status: 200 },
      ),
    );
    await vi.advanceTimersByTimeAsync(0);
    expect(document.querySelector(".history-state.active").textContent).toBe(
      "正在补采",
    );
    expect(document.body.textContent).toContain("后台最近心跳正常");
    expect(document.body.textContent).toContain("当前第 38 批");
    expect(
      document
        .querySelector(".history-metrics dd")
        .textContent.replace(/\s/g, ""),
    ).toBe("2/4项");
    expect(document.body.textContent).not.toContain("历史补采进度暂不可用");
  });

  it("卸载取消挂起请求并清理计时器，之后送达的响应不恢复面板", async () => {
    let signal;
    let deliverResponse;
    const fetch = vi.fn((url, options) => {
      signal = options.signal;
      return new Promise((resolve) => (deliverResponse = resolve));
    });
    const progress = await showProgress(
      { status: "running", alive: true },
      fetch,
    );
    app.unmount();
    app = null;
    expect(signal.aborted).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
    deliverResponse(new Response(JSON.stringify(progress), { status: 200 }));
    await vi.advanceTimersByTimeAsync(60000);
    expect(document.querySelector(".history-panel")).toBeNull();
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});
