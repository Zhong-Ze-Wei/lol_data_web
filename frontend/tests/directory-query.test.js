import { afterEach, describe, expect, it, vi } from "vitest";
import { createApp, h, nextTick } from "vue";
import { createMemoryHistory, createRouter, RouterView } from "vue-router";
import DirectoryView from "../src/views/DirectoryView.vue";
import applicationRouter from "../src/router/index.js";

let app;
afterEach(() => {
  app?.unmount();
  document.body.innerHTML = "";
  vi.unstubAllGlobals();
});

function response(collection, rows, overrides = {}) {
  return new Response(
    JSON.stringify({
      [collection]: rows,
      pagination: {
        page: 1,
        per_page: 2,
        total: 30,
        pages: 15,
        has_prev: false,
        has_next: true,
        prev_num: null,
        next_num: 2,
        ...overrides,
      },
    }),
    { status: 200 },
  );
}
async function show(path, fetcher) {
  vi.stubGlobal("fetch", vi.fn(fetcher));
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      ...["player", "match", "team", "hero"].map((kind) => ({
        path: `/${kind}`,
        component: DirectoryView,
        props: { kind },
      })),
      { path: "/:pathMatch(.*)*", component: { render: () => h("div") } },
    ],
  });
  await router.push(path);
  await router.isReady();
  const element = document.createElement("div");
  document.body.append(element);
  app = createApp({ render: () => h(RouterView) }).use(router);
  app.mount(element);
  await nextTick();
  return router;
}
function requestUrl() {
  return new URL(fetch.mock.calls.at(-1)[0], "http://localhost");
}
function input(name, value) {
  const element = document.querySelector(`[name="${name}"]`);
  element.value = value;
  element.dispatchEvent(new Event("input", { bubbles: true }));
}
function submit() {
  document
    .querySelector("form")
    .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
}
function button(text) {
  return [...document.querySelectorAll("button")].find(
    (item) => item.textContent.trim() === text,
  );
}
function bodyLinks() {
  return [...document.querySelectorAll("tbody .entity-name")].map((item) =>
    item.getAttribute("href"),
  );
}

describe("门户目录的全量查询与来源口径", () => {
  it.each(["player", "match", "team", "hero"])(
    "%s 目录的比较入口能解析到正式对比页面",
    async (kind) => {
      const collection = {
        player: "players",
        match: "matches",
        team: "teams",
        hero: "heroes",
      }[kind];
      await show(`/${kind}`, async () => response(collection, []));
      const link = [...document.querySelectorAll(".directory-sidebar a")].find(
        (item) => item.textContent.includes("比较选手表现"),
      );
      expect(link).toBeDefined();
      expect(applicationRouter.resolve(link.getAttribute("href")).name).toBe(
        "analytics",
      );
    },
  );

  it("选手搜索和排序交给后端，重置页码且前进后退还原 URL 条件", async () => {
    const router = await show(
      "/player?player_name=Old&page=4&per_page=2",
      async () =>
        response("players", [
          { name: "Zulu", appearance_count: 1, latest_match_date: null },
          { name: "Alpha", appearance_count: 99, latest_match_date: null },
        ]),
    );
    await vi.waitFor(() =>
      expect(document.querySelectorAll("tbody tr")).toHaveLength(2),
    );
    expect(bodyLinks()).toEqual(["/player/Zulu", "/player/Alpha"]);
    input("player_name", " Faker ");
    submit();
    await vi.waitFor(() =>
      expect(router.currentRoute.value.query.player_name).toBe("Faker"),
    );
    expect(requestUrl().searchParams.get("player_name")).toBe("Faker");
    expect(requestUrl().searchParams.get("per_page")).toBe("2");
    expect(requestUrl().searchParams.has("page")).toBe(false);
    expect(requestUrl().searchParams.get("sort")).toBe("appearance_count");
    const select = document.querySelector('[name="sort"]');
    select.value = "name";
    select.dispatchEvent(new Event("change", { bubbles: true }));
    await vi.waitFor(() =>
      expect(requestUrl().searchParams.get("sort")).toBe("name"),
    );
    router.back();
    await vi.waitFor(() =>
      expect(document.querySelector('[name="sort"]').value).toBe(
        "appearance_count",
      ),
    );
    router.back();
    await vi.waitFor(() =>
      expect(document.querySelector('[name="player_name"]').value).toBe("Old"),
    );
    expect(router.currentRoute.value.query.page).toBe("4");
    router.forward();
    await vi.waitFor(() =>
      expect(document.querySelector('[name="player_name"]').value).toBe(
        "Faker",
      ),
    );
  });

  it("位置待确认和中单向服务端提交，切换清除旧页码，重置清除所有筛选", async () => {
    const router = await show("/player?team_name=T1&page=6", async () =>
      response("players", [
        { name: "Known", position: null, appearance_count: 1 },
      ]),
    );
    await vi.waitFor(() =>
      expect(document.querySelectorAll("tbody tr")).toHaveLength(1),
    );
    button("位置待确认").click();
    await vi.waitFor(() =>
      expect(requestUrl().searchParams.get("position")).toBe("unknown"),
    );
    expect(router.currentRoute.value.query.page).toBeUndefined();
    expect(requestUrl().searchParams.get("team_name")).toBe("T1");
    expect(button("位置待确认").getAttribute("aria-pressed")).toBe("true");
    button("中单").click();
    await vi.waitFor(() =>
      expect(requestUrl().searchParams.get("position")).toBe("c"),
    );
    button("重置").click();
    await vi.waitFor(() => expect(router.currentRoute.value.query).toEqual({}));
    expect(button("全部位置").getAttribute("aria-pressed")).toBe("true");
    expect(document.querySelector('[name="team_name"]').value).toBe("");
  });

  it("最新赛程缺失时保留待确认，不把旧来源更新时间显示为比赛日期", async () => {
    await show("/player", async () =>
      response("players", [
        {
          name: "UnknownDate",
          latest_date: "2021-01-01",
          latest_match_date: null,
          appearance_count: 10,
        },
        {
          name: "Confirmed",
          latest_date: "2026-10-04",
          latest_match_date: "2022-01-23",
          appearance_count: 2,
        },
      ]),
    );
    await vi.waitFor(() =>
      expect(document.querySelectorAll("tbody tr")).toHaveLength(2),
    );
    const rows = document.querySelectorAll("tbody tr");
    expect(rows[0].querySelectorAll("td")[4].textContent).toBe("日期待确认");
    expect(rows[1].querySelectorAll("td")[4].textContent).toBe("2022-01-23");
    expect(document.querySelector(".archive-facts").textContent).toContain(
      "日期待确认",
    );
    expect(document.body.textContent).not.toContain("2021-01-01");
    expect(document.body.textContent).not.toContain("2026-10-04");
  });

  it("比赛关键词、赛事、双方和日期均全量请求，旧月份链接可编辑后沿用", async () => {
    const router = await show(
      "/match?start_date=2022-01&end_date=2022-02&page=3",
      async () =>
        response("matches", [
          {
            match_id: 28972,
            tournament_name: "2022 LCK春季赛",
            blue_team_name: "T1",
            red_team_name: "LSB",
            date: "2022-01-23",
            game_time: 2000,
            verified: true,
          },
        ]),
    );
    await vi.waitFor(() =>
      expect(document.querySelectorAll("tbody tr")).toHaveLength(1),
    );
    expect(document.querySelector('[name="date_from"]').value).toBe("2022-01");
    expect(document.querySelector('[name="date_to"]').value).toBe("2022-02");
    input("query", "28972");
    input("tournament_name", " LCK春季赛 ");
    input("team_name1", "T1");
    input("team_name2", "LSB");
    submit();
    await vi.waitFor(() =>
      expect(requestUrl().searchParams.get("query")).toBe("28972"),
    );
    expect(Object.fromEntries(requestUrl().searchParams)).toEqual({
      query: "28972",
      tournament_name: "LCK春季赛",
      team_name1: "T1",
      team_name2: "LSB",
      date_from: "2022-01",
      date_to: "2022-02",
    });
    expect(router.currentRoute.value.query.page).toBeUndefined();
    expect(document.querySelector(".results-header").textContent).toContain(
      "2022-01 至 2022-02",
    );
    expect(document.querySelector('a[href="/match/28972"]')).not.toBeNull();
    expect(document.querySelector("tbody").textContent).toContain(
      "2022 LCK春季赛",
    );
  });

  it("新日期参数存在时忽略旧月份，展示与服务端日期优先级一致", async () => {
    await show("/match?date_to=2024-12-31&start_date=2022-01", async () =>
      response("matches", []),
    );
    await vi.waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(document.querySelector('[name="date_from"]').value).toBe("");
    expect(document.querySelector('[name="date_to"]').value).toBe("2024-12-31");
    expect(document.querySelector(".results-header").textContent).toContain(
      "最早赛程 至 2024-12-31",
    );
  });

  it("基础战报缺队名和时长可查阅，未知身份不生成虚假战队链接", async () => {
    await show("/match?query=35121", async () =>
      response("matches", [
        {
          match_id: 35121,
          tournament_name: null,
          blue_team_name: null,
          red_team_name: "IMT",
          date: null,
          game_time: null,
          win_team_name: null,
          verified: true,
          source: "scoregg_metadata",
        },
      ]),
    );
    await vi.waitFor(() =>
      expect(document.querySelectorAll("tbody tr")).toHaveLength(1),
    );
    const text = document.querySelector("tbody").textContent;
    expect(text).toContain("日期待确认");
    expect(text).toContain("队伍待确认");
    expect(text).toContain("未记录");
    expect(text).toContain("基础战报");
    expect(document.querySelector('a[href="/team/null"]')).toBeNull();
    expect(document.querySelector('a[href="/team/undefined"]')).toBeNull();
    expect(document.querySelector('a[href="/team/IMT"]')).not.toBeNull();
    expect(document.querySelector('a[href="/match/35121"]')).not.toBeNull();
  });

  it("分页保留比赛筛选参数，不对当前页作筛选或把页大小误当总数", async () => {
    const router = await show(
      "/match?query=LSB&tournament_name=LCK&date_from=2022-01-01&per_page=2",
      async () =>
        response("matches", [
          {
            match_id: 1,
            blue_team_name: "Source A",
            red_team_name: "Source B",
          },
        ]),
    );
    await vi.waitFor(() =>
      expect(document.querySelectorAll("tbody tr")).toHaveLength(1),
    );
    expect(document.querySelector(".results-header").textContent).toContain(
      "30 场比赛",
    );
    // UI 信任后端结果，不在当前页上按关键词再次删除记录。
    expect(document.querySelector("tbody").textContent).toContain("Source A");
    button("下一页 →").click();
    await vi.waitFor(() =>
      expect(router.currentRoute.value.query.page).toBe("2"),
    );
    expect(Object.fromEntries(requestUrl().searchParams)).toEqual({
      query: "LSB",
      tournament_name: "LCK",
      date_from: "2022-01-01",
      per_page: "2",
      page: "2",
    });
  });

  it("英雄和战队仍使用各自服务端搜索，英雄只提供后端支持的 a–e 位置", async () => {
    const router = await show("/hero", async (url) =>
      new URL(url, "http://localhost").pathname.includes("/hero/")
        ? response("heroes", [
            {
              hero_name: "Ahri",
              matches_count: 4,
              position: "mid",
              win_rate: null,
            },
          ])
        : response("teams", [{ team_name: "T1", match_count: 10 }]),
    );
    await vi.waitFor(() =>
      expect(document.querySelectorAll("tbody tr")).toHaveLength(1),
    );
    expect(button("位置待确认")).toBeUndefined();
    input("hero_name", "Ahri");
    button("中单").click();
    await vi.waitFor(() =>
      expect(requestUrl().searchParams.get("position")).toBe("c"),
    );
    expect(requestUrl().searchParams.get("hero_name")).toBe("Ahri");
    expect(document.querySelector('a[href="/hero/Ahri"]')).not.toBeNull();
    await router.push("/team");
    await vi.waitFor(() =>
      expect(document.querySelector('[name="team_name"]')).not.toBeNull(),
    );
    input("team_name", "T1");
    submit();
    await vi.waitFor(() =>
      expect(requestUrl().pathname).toBe("/team/api/distinct"),
    );
    await vi.waitFor(() =>
      expect(requestUrl().searchParams.get("team_name")).toBe("T1"),
    );
    expect(document.querySelector('a[href="/team/T1"]')).not.toBeNull();
  });

  it("目录筛选取消旧请求，迟到的旧页数据不能覆盖新档案", async () => {
    const pending = [];
    const router = await show(
      "/player?player_name=Old",
      (url, options) =>
        new Promise((resolve) =>
          pending.push({ url, signal: options.signal, resolve }),
        ),
    );
    await vi.waitFor(() => expect(pending).toHaveLength(1));
    await router.push("/player?player_name=New");
    await vi.waitFor(() => expect(pending).toHaveLength(2));
    expect(pending[0].signal.aborted).toBe(true);
    pending[1].resolve(
      response("players", [{ name: "New", appearance_count: 1 }]),
    );
    await vi.waitFor(() =>
      expect(document.querySelector("tbody").textContent).toContain("New"),
    );
    pending[0].resolve(
      response("players", [{ name: "Old", appearance_count: 1 }]),
    );
    await nextTick();
    expect(document.querySelector("tbody").textContent).not.toContain("Old");
    expect(document.querySelector(".spotlight-name").textContent).toContain(
      "New",
    );
  });
});
