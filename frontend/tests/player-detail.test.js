import { afterEach, describe, expect, it, vi } from "vitest";
import { createApp, h } from "vue";
import { createMemoryHistory, createRouter, RouterView } from "vue-router";
import PlayerDetail from "../src/views/PlayerDetail.vue";

vi.mock("../src/components/Chart.vue", async () => {
  const { h } = await import("vue");
  return {
    default: {
      props: ["label"],
      setup: (props) => () =>
        h("div", { role: "img", "aria-label": props.label }),
    },
  };
});

let app;
afterEach(() => {
  app?.unmount();
  document.body.innerHTML = "";
  vi.unstubAllGlobals();
});

async function showPlayer(overrides = {}) {
  const profile = {
    name: "Faker",
    pic: null,
    main_position: "c",
    latest_match_date: "2026-09-12",
    stats: {
      totalMatches: 123,
      knownResults: 100,
      winRate: 45,
      avgKDA: "3.2/2.1/5.4",
      avgAtkM: 350,
      avgAtkMSamples: 80,
      heroPool: 20,
    },
    players: [
      {
        match_id: 10,
        date: "2020-04-01",
        hero: null,
        position: "c",
        result: null,
        kills: 0,
        deaths: 1,
        assists: 2,
        atk_m: null,
        money: null,
      },
    ],
    pagination: {
      page: 2,
      pages: 3,
      total: 123,
      has_prev: true,
      prev_num: 1,
      has_next: true,
      next_num: 3,
    },
    ...overrides,
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url) => {
      const data = String(url).includes("/analytics")
        ? {
            matches_count: 0,
            axes: [],
            percentiles: {},
            monthly: [],
            heroes: [],
          }
        : profile;
      return new Response(JSON.stringify(data), { status: 200 });
    }),
  );
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/player/:name", component: PlayerDetail },
      { path: "/:pathMatch(.*)*", component: { render: () => h("div") } },
    ],
  });
  await router.push("/player/Faker?page=2");
  await router.isReady();
  const container = document.createElement("div");
  document.body.append(container);
  app = createApp({ render: () => h(RouterView) }).use(router);
  app.mount(container);
  await vi.waitFor(() =>
    expect(document.querySelectorAll("tbody tr")).toHaveLength(1),
  );
  return { profile, router };
}

function fact(label) {
  return [...document.querySelectorAll(".detail-facts > div")]
    .find((row) => row.querySelector("dt").textContent === label)
    ?.querySelector("dd")
    .textContent.trim();
}

describe("选手门户档案的收录范围", () => {
  it("全档案最新确认日期不取当前页日期，分页后仍保持同一口径", async () => {
    const { router } = await showPlayer();
    expect(fact("已收录出场")).toBe("123 局");
    expect(fact("最新确认日期")).toBe("2026-09-12");
    expect(fact("已知胜负")).toBe("100 局");
    expect(document.querySelector("tbody td").textContent).toBe("2020-04-01");
    expect(document.body.textContent).toContain("不代表完整生涯");
    document.querySelectorAll(".pagination button")[1].click();
    await vi.waitFor(() =>
      expect(router.currentRoute.value.query.page).toBe("3"),
    );
    await vi.waitFor(() =>
      expect(
        fetch.mock.calls.some(([url]) => String(url).includes("page=3")),
      ).toBe(true),
    );
    await vi.waitFor(() => expect(fact("最新确认日期")).toBe("2026-09-12"));
  });

  it("未知角色、未确认日期和缺失指标不借出场记录补值，真实零样本保留", async () => {
    await showPlayer({
      main_position: null,
      latest_match_date: null,
      stats: {
        totalMatches: 123,
        knownResults: 0,
        winRate: null,
        avgKDA: null,
        avgAtkM: null,
        avgAtkMSamples: 0,
        heroPool: 0,
      },
    });
    expect(fact("最新确认日期")).toBe("—");
    expect(fact("已收录出场")).toBe("123 局");
    expect(fact("样本胜率")).toBe("—");
    expect(fact("分均伤害")).toBe("—");
    expect(fact("伤害有效样本")).toBe("0 局");
    expect(document.querySelector(".detail-identity .tag").textContent).toBe(
      "未知位置",
    );
    expect(document.querySelector(".profile-photo")).toBeNull();
    expect(document.querySelector("tbody td").textContent).toBe("2020-04-01");
  });
});
