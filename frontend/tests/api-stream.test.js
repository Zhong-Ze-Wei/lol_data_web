import { afterEach, describe, expect, it, vi } from "vitest";
import { streamAIQuery } from "../src/services/api.js";

afterEach(() => vi.unstubAllGlobals());
const first = {
  status: "ok",
  data: [{ player: "中文选手", kills: 0 }],
  explanation_status: "pending",
};
const final = {
  ...first,
  answer: "中文解读已完成。",
  explanation_status: "complete",
};

function mockStream(
  events,
  { byteByByte = false, trailingNewline = true } = {},
) {
  const encoded = new TextEncoder().encode(
    events.map((event) => JSON.stringify(event)).join("\n") +
      (trailingNewline ? "\n" : ""),
  );
  const response = new Response(
    new ReadableStream({
      start(controller) {
        if (byteByByte)
          for (const byte of encoded) controller.enqueue(Uint8Array.of(byte));
        else controller.enqueue(encoded);
        controller.close();
      },
    }),
    { headers: { "Content-Type": "application/x-ndjson" } },
  );
  const fetch = vi.fn().mockResolvedValue(response);
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

describe("AI 数据分阶段返回", () => {
  it("UTF8 中文逐字节拆块、跨行和末行没有换行时仍按顺序交付同次结果", async () => {
    const fetch = mockStream(
      [
        { type: "data", result: first },
        { type: "explanation", result: final },
        { type: "done" },
      ],
      { byteByByte: true, trailingNewline: false },
    );
    const onResult = vi.fn();
    const signal = new AbortController().signal;
    const body = {
      prompt: "完整中文问题",
      context: { plan: { entity: "player" } },
    };
    await expect(streamAIQuery({ body, signal, onResult })).resolves.toEqual(
      final,
    );
    expect(onResult.mock.calls).toEqual([
      [first, "data"],
      [final, "explanation"],
    ]);
    expect(fetch).toHaveBeenCalledOnce();
    expect(fetch).toHaveBeenCalledWith(
      "/api/ai/query-stream",
      expect.objectContaining({
        method: "POST",
        signal,
        body: JSON.stringify(body),
      }),
    );
  });

  it("数据立即交付，解读尚未返回时请求保持等待而不丢第一份快照", async () => {
    let controller;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          new ReadableStream({
            start(value) {
              controller = value;
            },
          }),
          { headers: { "Content-Type": "application/x-ndjson" } },
        ),
      ),
    );
    const onResult = vi.fn();
    let completed = false;
    const promise = streamAIQuery({ body: { prompt: "测试" }, onResult }).then(
      () => {
        completed = true;
      },
    );
    controller.enqueue(
      new TextEncoder().encode(
        JSON.stringify({ type: "data", result: first }) + "\n",
      ),
    );
    await vi.waitFor(() =>
      expect(onResult).toHaveBeenCalledWith(first, "data"),
    );
    expect(completed).toBe(false);
    controller.enqueue(
      new TextEncoder().encode(
        JSON.stringify({ type: "explanation", result: final }) +
          "\n" +
          JSON.stringify({ type: "done" }) +
          "\n",
      ),
    );
    controller.close();
    await promise;
    expect(completed).toBe(true);
  });

  it.each(
    [
      [],
      [{ type: "done" }],
      [{ type: "data", result: first }],
      [{ type: "data", result: first }, { type: "done" }],
      [{ type: "explanation", result: final }, { type: "done" }],
      [
        { type: "data", result: first },
        { type: "explanation", result: final },
      ],
    ].map((events) => ({ events })),
  )("拒绝没有数据、终止标记或完整解读的响应 %#", async ({ events }) => {
    mockStream(events);
    await expect(
      streamAIQuery({ body: { prompt: "测试" }, onResult: vi.fn() }),
    ).rejects.toMatchObject({ name: "ApiError", code: "incomplete_response" });
  });

  it("澄清或不请求解读的结果可只返回data和done", async () => {
    const result = {
      status: "needs_clarification",
      data: [],
      explanation_status: "skipped",
    };
    mockStream([{ type: "data", result }, { type: "done" }]);
    await expect(
      streamAIQuery({ body: { prompt: "谁最强" }, onResult: vi.fn() }),
    ).resolves.toEqual(result);
  });

  it("数据后的错误事件保留已经交付的结果，错误不触发第二个请求", async () => {
    const fetch = mockStream([
      { type: "data", result: first },
      { type: "error", code: 503, error: "解读暂时不可用" },
    ]);
    const onResult = vi.fn();
    await expect(
      streamAIQuery({ body: { prompt: "测试" }, onResult }),
    ).rejects.toMatchObject({ message: "解读暂时不可用", code: 503 });
    expect(onResult.mock.calls).toEqual([[first, "data"]]);
    expect(fetch).toHaveBeenCalledOnce();
  });

  it("首次HTTP错误仍读取JSON业务错误，不转发成空的成功数据", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ error: "问题超过1000字", code: 422 }), {
          status: 422,
        }),
      ),
    );
    const onResult = vi.fn();
    await expect(
      streamAIQuery({ body: { prompt: "测试" }, onResult }),
    ).rejects.toMatchObject({
      status: 422,
      code: 422,
      message: "问题超过1000字",
    });
    expect(onResult).not.toHaveBeenCalled();
  });

  it("网络中断和用户取消均保留原错误类型，客户端不自行重试", async () => {
    let controller;
    const signal = new AbortController();
    const fetch = vi.fn().mockResolvedValue(
      new Response(
        new ReadableStream({
          start(value) {
            controller = value;
          },
        }),
        { headers: { "Content-Type": "application/x-ndjson" } },
      ),
    );
    vi.stubGlobal("fetch", fetch);
    signal.signal.addEventListener("abort", () =>
      controller.error(new DOMException("用户取消", "AbortError")),
    );
    const promise = streamAIQuery({
      body: { prompt: "测试" },
      signal: signal.signal,
      onResult: vi.fn(),
    });
    signal.abort();
    await expect(promise).rejects.toMatchObject({ name: "AbortError" });
    expect(fetch).toHaveBeenCalledOnce();
  });

  it.each([
    { value: new TextEncoder().encode('{"type":') },
    { value: Uint8Array.of(255) },
  ])("无效JSON或UTF8响应会取消reader释放响应体 %#", async ({ value }) => {
    const cancel = vi.fn();
    const response = new Response(
      new ReadableStream({
        start(controller) {
          controller.enqueue(value);
          controller.enqueue(new TextEncoder().encode("\n"));
        },
        cancel,
      }),
      { headers: { "Content-Type": "application/x-ndjson" } },
    );
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));
    await expect(
      streamAIQuery({ body: { prompt: "测试" }, onResult: vi.fn() }),
    ).rejects.toMatchObject({ code: "incomplete_response" });
    expect(cancel).toHaveBeenCalledOnce();
    expect(response.body.locked).toBe(false);
  });

  it("收到done即取消仍开放的响应体，无需继续等连接关闭", async () => {
    const cancel = vi.fn();
    const result = { ...first, explanation_status: "skipped" };
    const response = new Response(
      new ReadableStream({
        start(controller) {
          controller.enqueue(
            new TextEncoder().encode(
              JSON.stringify({ type: "data", result }) +
                "\n" +
                JSON.stringify({ type: "done" }) +
                "\n",
            ),
          );
        },
        cancel,
      }),
      { headers: { "Content-Type": "application/x-ndjson" } },
    );
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));
    await expect(
      streamAIQuery({ body: { prompt: "测试" }, onResult: vi.fn() }),
    ).resolves.toEqual(result);
    expect(cancel).toHaveBeenCalledOnce();
    expect(response.body.locked).toBe(false);
  });

  it("HTTP200的错误内容类型也会释放开放响应，不将HTML当成分析结果", async () => {
    const cancel = vi.fn();
    const response = new Response(
      new ReadableStream({
        start(controller) {
          controller.enqueue(new TextEncoder().encode("<html>error</html>"));
        },
        cancel,
      }),
      { headers: { "Content-Type": "text/html" } },
    );
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));
    await expect(
      streamAIQuery({ body: { prompt: "测试" }, onResult: vi.fn() }),
    ).rejects.toMatchObject({ code: "incomplete_response" });
    expect(cancel).toHaveBeenCalledOnce();
    expect(response.body.locked).toBe(false);
  });
});
