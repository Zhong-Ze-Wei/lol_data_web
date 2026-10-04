import { afterEach, describe, expect, it, vi } from "vitest";
import { createApp, h } from "vue";
import { createMemoryHistory, createRouter, RouterView } from "vue-router";
import MatchDetail from "../src/views/MatchDetail.vue";

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

async function showMatch({
  count,
  verified,
  duration,
  metrics = {},
  sideBasis = "scoregg_red_blue",
}) {
  const players = Array.from({ length: count }, (_, index) => ({
    name: `已收录选手${index + 1}`,
    team_name: index < 5 ? "蓝队" : "红队",
    position: "a",
    hero: null,
    kills: 2,
    deaths: 1,
    assists: 3,
    kda: 5,
    part: 50,
    atk: 12000,
    atk_m: duration ? 400 : null,
    hits: 180,
    money: 9000,
    ...metrics,
  }));
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            match: {
              match_id: "qa",
              verified,
              game_time: duration,
              blue_team_name: "蓝队",
              red_team_name: "红队",
              win_team_name: "蓝队",
              date: null,
              side_basis: sideBasis,
            },
            players,
            blue_team: null,
            red_team: null,
          }),
          { status: 200 },
        ),
    ),
  );
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/match/:match_id", component: MatchDetail },
      { path: "/:pathMatch(.*)*", component: { render: () => h("div") } },
    ],
  });
  await router.push("/match/qa");
  await router.isReady();
  const element = document.createElement("div");
  document.body.append(element);
  app = createApp({ render: () => h(RouterView) }).use(router);
  app.mount(element);
  await vi.waitFor(() =>
    expect(document.querySelectorAll("tbody tr")).toHaveLength(count),
  );
}

describe("比赛详情数据质量", () => {
  it("基础战报按来源双方顺序展示，不猜红蓝方和选手位置", async () => {
    await showMatch({
      count: 10,
      verified: true,
      duration: null,
      sideBasis: "metadata_team_a_b",
      metrics: {
        position: null,
        atk: null,
        atk_m: null,
        money: null,
        hits: null,
      },
    });
    expect(
      [...document.querySelectorAll(".score-team .eyebrow")].map(
        (element) => element.textContent,
      ),
    ).toEqual(["队伍 A", "队伍 B"]);
    expect(
      [...document.querySelectorAll(".analysis-grid .tag")].map(
        (element) => element.textContent,
      ),
    ).toEqual(["队伍 A", "队伍 B"]);
    expect(
      [...document.querySelectorAll(".section-space h2")]
        .map((element) => element.textContent)
        .filter((label) => label.endsWith("选手数据")),
    ).toEqual(["队伍 A选手数据", "队伍 B选手数据"]);
    const notice = document.querySelector(".match-quality-notice").textContent;
    expect(notice).toContain("红蓝方尚未确认，双方按来源顺序展示");
    expect(notice).toContain("部分选手位置待确认");
    expect(notice).toContain("缺少可信比赛时长");
    expect(notice).not.toContain("阵容有缺项");
    for (const row of document.querySelectorAll("tbody tr"))
      expect(row.querySelectorAll("td")[1].textContent).toBe("未记录");
    expect(document.querySelector('[role="img"]')).toBeNull();
    expect(document.querySelector(".victory").textContent).toBe("胜利");
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it("完整战报仍使用真实红蓝方，保留已确认位置和精确时长", async () => {
    await showMatch({ count: 10, verified: true, duration: 1800 });
    expect(
      [...document.querySelectorAll(".score-team .eyebrow")].map(
        (element) => element.textContent,
      ),
    ).toEqual(["蓝方", "红方"]);
    expect(document.querySelector(".score-center strong").textContent).toBe(
      "30:00",
    );
    expect(document.querySelector(".match-quality-notice")).toBeNull();
    for (const row of document.querySelectorAll("tbody tr"))
      expect(row.querySelectorAll("td")[1].textContent).toBe("上单");
  });
  it("公开9人战报和未知时长只展示已确认选手，并准确说明分均缺失", async () => {
    await showMatch({ count: 9, verified: true, duration: null });
    expect(document.querySelector(".page-heading").textContent).toContain(
      "已收录 9/10 位选手",
    );
    expect(document.querySelectorAll(".match-quality-notice")).toHaveLength(1);
    expect(
      document.querySelector(".match-quality-notice").textContent,
    ).toContain("公开战报阵容有缺项");
    expect(
      document.querySelector(".match-quality-notice").textContent,
    ).toContain("缺少可信比赛时长，分均指标未计算");
    for (const row of document.querySelectorAll("tbody tr"))
      expect(row.querySelectorAll("td")[6].textContent).toBe("—");
    expect(
      document.querySelector('[role="img"]').getAttribute("aria-label"),
    ).toContain("已收录选手");
  });
  it("历史导入的缺阵容不误称公开源站缺项", async () => {
    await showMatch({ count: 9, verified: false, duration: 1800 });
    expect(
      document.querySelector(".match-quality-notice").textContent,
    ).toContain("历史记录阵容不完整");
    expect(
      document.querySelector(".match-quality-notice").textContent,
    ).not.toContain("公开战报");
  });
  it("正常10人及可信时长不显示多余质量提示", async () => {
    await showMatch({ count: 10, verified: true, duration: 1800 });
    expect(document.querySelector(".page-heading").textContent).toContain(
      "已收录 10/10 位选手",
    );
    expect(document.querySelector(".match-quality-notice")).toBeNull();
  });
  it("整组统计缺失显示空值并说明原因，不绘制零伤害图", async () => {
    await showMatch({
      count: 10,
      verified: true,
      duration: 1800,
      metrics: { atk: null, atk_m: null, money: null, hits: null },
    });
    expect(
      document.querySelector(".match-quality-notice").textContent,
    ).toContain("部分伤害、经济、补刀数据缺失，空值未计为零");
    expect(document.querySelector('[role="img"]')).toBeNull();
    expect(document.body.textContent).toContain(
      "本场没有可信伤害记录，未生成伤害图",
    );
    for (const row of document.querySelectorAll("tbody tr"))
      for (const cell of Array.from(row.querySelectorAll("td")).slice(6))
        expect(cell.textContent).toBe("—");
  });
  it("可信零值仍显示0，伤害图保留", async () => {
    await showMatch({
      count: 10,
      verified: true,
      duration: 1800,
      metrics: { atk: 0, atk_m: 0, money: 0, hits: 0 },
    });
    expect(document.querySelector(".match-quality-notice")).toBeNull();
    expect(document.querySelector('[role="img"]')).not.toBeNull();
    for (const row of document.querySelectorAll("tbody tr"))
      for (const cell of Array.from(row.querySelectorAll("td")).slice(6))
        expect(cell.textContent).toBe("0");
  });
});
