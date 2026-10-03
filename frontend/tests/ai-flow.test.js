import { afterEach, describe, expect, it, vi } from "vitest";
import { createApp, h, nextTick } from "vue";
import { createMemoryHistory, createRouter, RouterView } from "vue-router";
import Home from "../src/views/Home.vue";

let app;
const originalScroll = Element.prototype.scrollIntoView;
afterEach(() => {
  app?.unmount();
  document.body.innerHTML = "";
  vi.unstubAllGlobals();
  Element.prototype.scrollIntoView = originalScroll;
});

async function mountClarificationFlow(responses) {
  const calls = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path, options) => {
      let payload;
      if (path.startsWith("/api/ai/query")) {
        calls.push(JSON.parse(options.body));
        payload = { result: responses[calls.length - 1] };
      } else if (path.startsWith("/api/stats"))
        payload = {
          stats: { matches: 0, players: 0, teams: 0, verified_matches: 0 },
        };
      else if (path.startsWith("/api/recent-matches"))
        payload = { matches: [] };
      else payload = { players: [] };
      return new Response(JSON.stringify(payload), { status: 200 });
    }),
  );
  Element.prototype.scrollIntoView = vi.fn();
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
  return calls;
}

async function sendPrompt(value) {
  if (value) {
    const input = document.querySelector("#ai-prompt");
    input.value = value;
    input.dispatchEvent(new Event("input", { bubbles: true }));
  }
  await nextTick();
  document
    .querySelector(".ai-panel form")
    .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  await nextTick();
  await vi.waitFor(() =>
    expect(document.querySelector(".ai-status")).not.toBeNull(),
  );
  await nextTick();
}

describe("AI 追问与澄清操作", () => {
  it("首次范围问题点选指标后，完整保留赛年、赛事与核验条件再发送", async () => {
    const question = "仅2014年已确认赛程且已核验的LPL比赛，谁最强？";
    const selected = question + "\n补充比较口径：同为中单，按平均单局KDA比较。";
    const calls = await mountClarificationFlow([
      {
        status: "needs_clarification",
        question,
        answer: "请明确比较指标和位置。",
        context: null,
        data: [],
        clarification: {
          question: "请明确比较指标和位置。",
          choices: [{ label: "中单平均 KDA", prompt: selected }],
        },
      },
      {
        status: "empty",
        question: selected,
        answer: "当前已核验范围没有达到门槛的样本。",
        data: [],
        context: null,
      },
    ]);
    await sendPrompt(question);
    expect(calls).toEqual([{ prompt: question }]);
    document.querySelector(".ai-clarification button").click();
    await nextTick();
    expect(document.querySelector("#ai-prompt").value).toBe(selected);
    expect(calls).toHaveLength(1);
    await sendPrompt();
    expect(calls[1]).toEqual({ prompt: selected });
  });

  it("长问题没有安全点选选项时提示编辑，保留完整原文直到用户修改后发送", async () => {
    const original = "仅2014年已确认赛程且已核验的LPL比赛，谁最强？";
    const question = original + "。".repeat(1000 - original.length);
    const edited = original + "\n补充比较口径：同为中单，按平均单局KDA比较。";
    const calls = await mountClarificationFlow([
      {
        status: "needs_clarification",
        question,
        answer: "补充比较口径后会超过1000字，请先精简原问题并保留原条件。",
        data: [],
        context: null,
        clarification: {
          question: "请先精简原问题并保留原条件。",
          choices: [],
        },
      },
      {
        status: "empty",
        question: edited,
        answer: "没有匹配数据。",
        data: [],
        context: null,
      },
    ]);
    await sendPrompt(question);
    expect(calls).toEqual([{ prompt: question }]);
    expect(document.querySelector("#ai-prompt").value).toBe(question);
    expect(document.querySelector(".ai-clarification button")).toBeNull();
    expect(document.querySelector(".ai-clarification").textContent).toContain(
      "请在上方编辑问题后重新发送。",
    );
    expect(
      document.querySelector(".ai-clarification").textContent,
    ).not.toContain("选择一个条件");
    await sendPrompt(edited);
    expect(calls[1]).toEqual({ prompt: edited });
  });

  it("选项仅填入问题；由用户发送，并可主动清除续问条件", async () => {
    const calls = [];
    const context = { plan: { entity: "players", metrics: ["avg_kda"] } };
    const responses = [
      {
        status: "ok",
        question: "选手KDA",
        answer: "根据数据库完成查询。",
        data: [{ player: "选手甲", avg_kda: 4 }],
        columns: [
          { key: "player", label: "选手", type: "string" },
          { key: "avg_kda", label: "平均单局 KDA", type: "number" },
        ],
        assumptions: ["只统计已收录的选手出场记录。"],
        context,
        followups: [{ label: "只看今年", prompt: "只看今年" }],
      },
      {
        status: "needs_clarification",
        question: "只看今年",
        answer: "请选择日期口径。",
        data: [],
        context,
        clarification: {
          question: "按哪种日期统计？",
          choices: [{ label: "确认赛程", prompt: "按确认赛程统计今年选手KDA" }],
        },
      },
      {
        status: "empty",
        question: "新查询",
        answer: "没有匹配数据。",
        data: [],
        context: null,
      },
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (path, options) => {
        let payload;
        if (path.startsWith("/api/ai/query")) {
          calls.push(JSON.parse(options.body));
          payload = { result: responses[calls.length - 1] };
        } else if (path.startsWith("/api/stats"))
          payload = {
            stats: { matches: 0, players: 0, teams: 0, verified_matches: 0 },
          };
        else if (path.startsWith("/api/recent-matches"))
          payload = { matches: [] };
        else payload = { players: [] };
        return new Response(JSON.stringify(payload), { status: 200 });
      }),
    );
    Element.prototype.scrollIntoView = vi.fn();
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
    function fill(value) {
      const input = document.querySelector("#ai-prompt");
      input.value = value;
      input.dispatchEvent(new Event("input", { bubbles: true }));
    }
    async function send(value) {
      if (value) fill(value);
      await nextTick();
      document
        .querySelector(".ai-panel form")
        .dispatchEvent(
          new Event("submit", { bubbles: true, cancelable: true }),
        );
      await nextTick();
      await vi.waitFor(() =>
        expect(document.querySelector(".ai-status")).not.toBeNull(),
      );
      await nextTick();
    }
    await send("选手KDA");
    expect(calls).toEqual([{ prompt: "选手KDA" }]);
    expect(document.querySelector(".ai-assumptions").open).toBe(false);
    expect(document.querySelector(".ai-interpretation").open).toBe(false);
    document.querySelector(".ai-followups button").click();
    await nextTick();
    expect(document.querySelector("#ai-prompt").value).toBe("只看今年");
    expect(calls).toHaveLength(1);
    await send();
    expect(calls[1]).toEqual({ prompt: "只看今年", context });
    expect(document.querySelector(".ai-status").textContent).toBe(
      "需要补充条件",
    );
    expect(document.querySelector(".ai-interpretation")).toBeNull();
    expect(document.querySelector(".ai-answer").textContent).toContain(
      "请选择日期口径",
    );
    document.querySelector(".ai-clarification button").click();
    await nextTick();
    expect(document.querySelector("#ai-prompt").value).toBe(
      "按确认赛程统计今年选手KDA",
    );
    expect(calls).toHaveLength(2);
    document.querySelector(".query-actions .text-button").click();
    await nextTick();
    await send("新查询");
    expect(calls[2]).toEqual({ prompt: "新查询" });
    expect(document.querySelector(".ai-status").textContent).toBe(
      "没有匹配数据",
    );
  });
});
