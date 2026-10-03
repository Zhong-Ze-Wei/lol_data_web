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

describe("AI 追问与澄清操作", () => {
  it("选项仅填入问题；由用户发送，并可主动清除续问条件", async () => {
    const calls = [];
    const context = { plan: { entity: "players", metrics: ["avg_kda"] } };
    const responses = [
      {
        status: "ok",
        question: "选手KDA",
        answer: "根据数据库完成查询。",
        data: [],
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
    document.querySelector(".ai-followups button").click();
    await nextTick();
    expect(document.querySelector("#ai-prompt").value).toBe("只看今年");
    expect(calls).toHaveLength(1);
    await send();
    expect(calls[1]).toEqual({ prompt: "只看今年", context });
    expect(document.querySelector(".ai-status").textContent).toBe(
      "需要补充条件",
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
