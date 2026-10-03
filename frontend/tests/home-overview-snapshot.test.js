import { afterEach, describe, expect, it, vi } from "vitest";
import { createApp, h, nextTick } from "vue";
import { createMemoryHistory, createRouter, RouterView } from "vue-router";
import Home from "../src/views/Home.vue";

let app;
afterEach(() => {
  app?.unmount();
  app = null;
  document.body.innerHTML = "";
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function response(value) {
  return new Response(JSON.stringify(value), { status: 200 });
}

function snapshot(verified, overview, updatedAt = "2026-10-03T23:00:00Z") {
  return {
    updated_at: updatedAt,
    overview_stats: overview,
    counts: {
      catalog: { total: 3 },
      series: { total: 5 },
      results: { verified },
    },
    worker: { status: "stopped", alive: false },
  };
}

async function showHome(statsLoader, historyLoader) {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-10-03T23:00:00Z"));
  const fetch = vi.fn((url, options) => {
    if (url === "/api/stats") return statsLoader(options);
    if (url === "/api/sync/history") return historyLoader(options);
    return Promise.resolve(response({ matches: [], players: [] }));
  });
  vi.stubGlobal("fetch", fetch);
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/", component: Home },
      { path: "/:pathMatch(.*)*", component: { render: () => h("div") } },
    ],
  });
  await router.push("/");
  await router.isReady();
  const element = document.createElement("div");
  document.body.append(element);
  app = createApp({ render: () => h(RouterView) }).use(router);
  app.mount(element);
  await vi.advanceTimersByTimeAsync(0);
  await nextTick();
  return fetch;
}

function overviewNumbers() {
  return [...document.querySelectorAll(".overview-stat strong")].map(
    (element) => element.textContent,
  );
}

const oldStats = { matches: 3, players: 2, teams: 2, verified_matches: 1 };
const cachedStats = { matches: 15, players: 7, teams: 3, verified_matches: 11 };
const newStats = { matches: 30, players: 12, teams: 4, verified_matches: 22 };

describe("首页总览与目录覆盖读取同一快照", () => {
  it.each(["success", "failure"])(
    "初始总览仍挂起时先显示history同快照统计，迟来的stats %s不覆盖或隐藏它",
    async (ending) => {
      let finishStats;
      let rejectStats;
      const fetch = await showHome(
        () =>
          new Promise((resolve, reject) => {
            finishStats = resolve;
            rejectStats = reject;
          }),
        async () => response(snapshot(20, newStats)),
      );
      expect(overviewNumbers()).toEqual(["30", "12", "4", "22"]);
      expect(
        document.querySelectorAll(".history-metrics dd")[2].textContent,
      ).toContain("20");
      expect(document.body.textContent).toContain(
        "总览统计更新 2026-10-04 07:00:00",
      );
      if (ending === "success") finishStats(response({ stats: oldStats }));
      else rejectStats(new Error("旧总览连接中断"));
      await vi.advanceTimersByTimeAsync(0);
      expect(overviewNumbers()).toEqual(["30", "12", "4", "22"]);
      expect(document.body.textContent).not.toContain("旧总览连接中断");
      expect(
        fetch.mock.calls.filter(([url]) => url === "/api/stats"),
      ).toHaveLength(1);
      expect(fetch.mock.calls.some(([url]) => url.startsWith("/api/ai"))).toBe(
        false,
      );
    },
  );

  it("history首次失败时使用原stats，之后同响应同步更新四项总览和目录核验数", async () => {
    let finishHistory;
    const history = vi
      .fn()
      .mockRejectedValueOnce(new Error("目录暂时不可用"))
      .mockImplementationOnce(
        () => new Promise((resolve) => (finishHistory = resolve)),
      );
    const fetch = await showHome(
      async () => response({ stats: oldStats }),
      history,
    );
    expect(overviewNumbers()).toEqual(["3", "2", "2", "1"]);
    await vi.advanceTimersByTimeAsync(30000);
    expect(overviewNumbers()).toEqual(["3", "2", "2", "1"]);
    finishHistory(response(snapshot(20, newStats, "2026-10-03T23:00:30Z")));
    await vi.advanceTimersByTimeAsync(0);
    expect(overviewNumbers()).toEqual(["30", "12", "4", "22"]);
    expect(
      document.querySelectorAll(".history-metrics dd")[2].textContent,
    ).toContain("20");
    expect(document.body.textContent).toContain(
      "总览统计更新 2026-10-04 07:00:30",
    );
    expect(
      fetch.mock.calls.filter(([url]) => url === "/api/stats"),
    ).toHaveLength(1);
  });

  it("刷新失败和挂起时保留同快照缓存与时间，下一次成功一起更新两处数字", async () => {
    let finishHistory;
    let pendingSignal;
    const history = vi
      .fn()
      .mockResolvedValueOnce(response(snapshot(10, cachedStats)))
      .mockRejectedValueOnce(new Error("覆盖读取失败"))
      .mockImplementationOnce((options) => {
        pendingSignal = options.signal;
        return new Promise((resolve) => (finishHistory = resolve));
      });
    const fetch = await showHome(
      async () => response({ stats: oldStats }),
      history,
    );
    expect(overviewNumbers()).toEqual(["15", "7", "3", "11"]);
    await vi.advanceTimersByTimeAsync(30000);
    expect(overviewNumbers()).toEqual(["15", "7", "3", "11"]);
    expect(
      document.querySelectorAll(".history-metrics dd")[2].textContent,
    ).toContain("10");
    expect(document.body.textContent).toContain(
      "总览统计更新 2026-10-04 07:00:00",
    );
    expect(document.body.textContent).toContain("历史补采进度暂不可用");
    await vi.advanceTimersByTimeAsync(75000);
    expect(history).toHaveBeenCalledTimes(3);
    expect(pendingSignal.aborted).toBe(false);
    expect(overviewNumbers()).toEqual(["15", "7", "3", "11"]);
    expect(document.body.textContent).toContain(
      "总览统计更新 2026-10-04 07:00:00",
    );
    finishHistory(response(snapshot(20, newStats, "2026-10-03T23:01:45Z")));
    await vi.advanceTimersByTimeAsync(0);
    expect(overviewNumbers()).toEqual(["30", "12", "4", "22"]);
    expect(
      document.querySelectorAll(".history-metrics dd")[2].textContent,
    ).toContain("20");
    expect(document.body.textContent).toContain(
      "总览统计更新 2026-10-04 07:01:45",
    );
    expect(document.body.textContent).not.toContain("历史补采进度暂不可用");
    expect(
      fetch.mock.calls.filter(([url]) => url === "/api/stats"),
    ).toHaveLength(1);
  });

  it("卸载取消两路挂起请求，迟来history响应不重新更新页面或发起轮询", async () => {
    let statsSignal;
    let historySignal;
    let finishHistory;
    const fetch = await showHome(
      (options) => {
        statsSignal = options.signal;
        return new Promise(() => {});
      },
      (options) => {
        historySignal = options.signal;
        return new Promise((resolve) => (finishHistory = resolve));
      },
    );
    app.unmount();
    app = null;
    expect(statsSignal.aborted).toBe(true);
    expect(historySignal.aborted).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
    finishHistory(response(snapshot(20, newStats)));
    await vi.advanceTimersByTimeAsync(60000);
    expect(document.querySelector(".overview-stats")).toBeNull();
    expect(
      fetch.mock.calls.filter(([url]) => url === "/api/sync/history"),
    ).toHaveLength(1);
  });
});
