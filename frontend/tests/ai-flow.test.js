import { afterEach, describe, expect, it, vi } from "vitest";
import { createApp, h, nextTick } from "vue";
import { createMemoryHistory, createRouter, RouterView } from "vue-router";
import Home from "../src/views/Home.vue";

vi.mock("../src/components/Chart.vue", () => ({
  __esModule: true,
  default: {
    props: ["label"],
    render() {
      return h("div", { class: "tested-ai-chart" }, this.label);
    },
  },
}));

let app;
function streamResponse(result) {
  return new Response(
    JSON.stringify({
      type: "data",
      result: { ...result, explanation_status: "skipped" },
    }) +
      "\n" +
      JSON.stringify({ type: "done" }) +
      "\n",
    { headers: { "Content-Type": "application/x-ndjson" } },
  );
}
function controlledResponse() {
  let controller;
  const response = new Response(
    new ReadableStream({
      start(value) {
        controller = value;
      },
    }),
    { headers: { "Content-Type": "application/x-ndjson" } },
  );
  return {
    response,
    send(event) {
      controller.enqueue(
        new TextEncoder().encode(JSON.stringify(event) + "\n"),
      );
    },
    close() {
      controller.close();
    },
  };
}
function dataResult() {
  return {
    status: "ok",
    question: "2016年已核验选手KDA",
    answer: "",
    explanation_status: "pending",
    data: [{ player: "选手甲", avg_kda: 4 }],
    columns: [
      { key: "player", label: "选手", type: "string" },
      { key: "avg_kda", label: "平均KDA", type: "number" },
    ],
    chart: {
      type: "bar",
      x: "player",
      series: [{ key: "avg_kda", label: "平均KDA" }],
    },
    evidence: {
      matches: 20,
      rows: 20,
      verified_matches: 20,
      model_calls: 1,
      grain: "选手单局出场",
    },
    assumptions: ["仅统计已核验出场。"],
    context: {
      plan: {
        entity: "players",
        metrics: ["avg_kda"],
        filters: { verified_only: true },
      },
    },
    followups: [{ label: "按英雄拆分", prompt: "保持条件，按英雄拆分" }],
  };
}
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
        const result = responses[calls.length - 1];
        return result instanceof Response ? result : streamResponse(result);
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
  it("先展示表格、证据和图表；解读等待时可继续填入追问，完成后保留同份数据与条件", async () => {
    const stream = controlledResponse();
    const initial = dataResult();
    const calls = await mountClarificationFlow([
      stream.response,
      { status: "empty", data: [], answer: "没有数据", context: null },
    ]);
    stream.send({ type: "data", result: initial });
    await sendPrompt(initial.question);
    expect(document.querySelector(".ai-data-section").textContent).toContain(
      "选手甲",
    );
    expect(document.querySelector(".ai-evidence").textContent).toContain("20");
    await vi.waitFor(() =>
      expect(document.querySelector(".tested-ai-chart")).not.toBeNull(),
    );
    expect(document.querySelector(".ai-status").textContent).toBe(
      "数据已就绪，正在解读",
    );
    expect(document.querySelector(".ai-interpretation")).toBeNull();
    expect(document.querySelector("#ai-prompt").disabled).toBe(false);
    expect(document.querySelector(".ai-panel .state-box")).toBeNull();
    document.querySelector(".ai-followups button").click();
    await nextTick();
    expect(document.querySelector("#ai-prompt").value).toBe(
      "保持条件，按英雄拆分",
    );
    expect(calls).toHaveLength(1);
    stream.send({
      type: "explanation",
      result: {
        ...initial,
        answer: "完整解读内容。",
        explanation_status: "complete",
        evidence: {
          ...initial.evidence,
          model_calls: 2,
          timings_ms: { writer: 100 },
        },
      },
    });
    stream.send({ type: "done" });
    stream.close();
    await vi.waitFor(() =>
      expect(document.querySelector(".ai-status").textContent).toBe("分析完成"),
    );
    expect(document.querySelector(".ai-interpretation").textContent).toContain(
      "完整解读内容",
    );
    expect(document.querySelector(".ai-data-section").textContent).toContain(
      "选手甲",
    );
    await sendPrompt();
    expect(calls[1]).toEqual({
      prompt: "保持条件，按英雄拆分",
      context: initial.context,
    });
  });

  it("数据之后断流保留表与条件，明确解读未完成且没有自动重试", async () => {
    const stream = controlledResponse();
    const initial = dataResult();
    const calls = await mountClarificationFlow([
      stream.response,
      { status: "empty", answer: "没有数据", data: [], context: null },
    ]);
    stream.send({ type: "data", result: initial });
    stream.close();
    await sendPrompt(initial.question);
    await vi.waitFor(() =>
      expect(document.querySelector(".ai-status").textContent).toBe(
        "数据已完成，文字解读未完成",
      ),
    );
    expect(document.querySelector(".ai-data-section").textContent).toContain(
      "选手甲",
    );
    expect(document.querySelector(".ai-evidence").textContent).toContain("20");
    expect(calls).toHaveLength(1);
    document.querySelector(".ai-followups button").click();
    await nextTick();
    await sendPrompt();
    expect(calls[1].context).toEqual(initial.context);
  });

  it("新问题取消旧解读；迟到旧流不会重置新查询loading、表格或上下文", async () => {
    const previous = controlledResponse();
    const current = controlledResponse();
    const initial = dataResult();
    const calls = await mountClarificationFlow([
      previous.response,
      current.response,
    ]);
    previous.send({ type: "data", result: initial });
    await sendPrompt(initial.question);
    const oldSignal = fetch.mock.calls.find(
      ([path]) => path === "/api/ai/query-stream",
    )[1].signal;
    document.querySelector(".query-actions .text-button").click();
    await nextTick();
    expect(oldSignal.aborted).toBe(true);
    const sending = sendPrompt("新问题");
    await vi.waitFor(() => expect(calls).toHaveLength(2));
    expect(calls[1]).toEqual({ prompt: "新问题" });
    previous.send({
      type: "explanation",
      result: { ...initial, explanation_status: "complete", answer: "旧解读" },
    });
    previous.send({ type: "done" });
    previous.close();
    await nextTick();
    expect(document.querySelector("#ai-prompt").disabled).toBe(true);
    expect(document.querySelector(".ai-data-section")).toBeNull();
    const updated = {
      ...initial,
      question: "新问题",
      data: [{ player: "选手乙", avg_kda: 8 }],
      context: { plan: { entity: "players", filters: {} } },
      explanation_status: "skipped",
    };
    current.send({ type: "data", result: updated });
    current.send({ type: "done" });
    current.close();
    await sending;
    expect(document.querySelector(".ai-data-section").textContent).toContain(
      "选手乙",
    );
    expect(
      document.querySelector(".ai-data-section").textContent,
    ).not.toContain("选手甲");
    expect(
      document.querySelector(".ai-answer")?.textContent || "",
    ).not.toContain("旧解读");
  });

  it("解读服务失败时保留返回数据，提供数据摘要而不标成解读完成", async () => {
    const stream = controlledResponse();
    const initial = dataResult();
    await mountClarificationFlow([stream.response]);
    stream.send({ type: "data", result: initial });
    stream.send({
      type: "explanation",
      result: {
        ...initial,
        answer: "样本20局。",
        explanation_status: "unavailable",
        assumptions: [
          ...initial.assumptions,
          "文字解读暂不可用，数据查询已完成。",
        ],
      },
    });
    stream.send({ type: "done" });
    stream.close();
    await sendPrompt(initial.question);
    expect(document.querySelector(".ai-status").textContent).toBe(
      "数据已完成，文字解读未完成",
    );
    expect(
      document.querySelector(".ai-interpretation summary").textContent,
    ).toBe("查看数据摘要");
    expect(document.querySelector(".ai-data-section").textContent).toContain(
      "选手甲",
    );
    expect(document.querySelector(".ai-assumptions").textContent).toContain(
      "文字解读暂不可用",
    );
  });

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
          return streamResponse(responses[calls.length - 1]);
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
