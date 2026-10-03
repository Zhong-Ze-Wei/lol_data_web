import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiUrl, request } from "../src/services/api.js";

afterEach(() => vi.unstubAllGlobals());
describe("API 请求", () => {
  it("编码中文与特殊符号，并保留有效零值", () => {
    expect(
      apiUrl("/player/api/list", {
        player_name: "A & 中文",
        page: 0,
        empty: "",
        nil: null,
      }),
    ).toBe("/player/api/list?player_name=A+%26+%E4%B8%AD%E6%96%87&page=0");
  });
  it("发送完整 AI 问题，并传递取消信号", async () => {
    const signal = new AbortController().signal;
    const fetch = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ result: { answer: "答案", data: [] } })),
      );
    vi.stubGlobal("fetch", fetch);
    const body = { prompt: "中文问题".repeat(100) };
    await expect(
      request("/api/ai/query", { method: "POST", body, signal }),
    ).resolves.toEqual({ result: { answer: "答案", data: [] } });
    expect(fetch).toHaveBeenCalledWith(
      "/api/ai/query",
      expect.objectContaining({
        signal,
        method: "POST",
        body: JSON.stringify(body),
      }),
    );
  });
  it("将未配置 AI 的结构化 503 错误转换为可读错误", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response(
            JSON.stringify({
              error: { code: "ai_not_configured", message: "AI 尚未配置" },
            }),
            { status: 503 },
          ),
        ),
    );
    await expect(request("/api/ai/query")).rejects.toMatchObject({
      name: "ApiError",
      status: 503,
      code: "ai_not_configured",
      message: "AI 尚未配置",
    });
  });
  it("空结果保持空数组，不把 200 当成错误", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response(
            JSON.stringify({ players: [], pagination: { page: 1, pages: 0 } }),
          ),
        ),
    );
    await expect(request("/player/api/list")).resolves.toMatchObject({
      players: [],
    });
  });
  it("HTML 错误页不会泄露原始 HTML，也不会当作成功结果", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response("<html>internal traceback</html>", { status: 500 }),
        ),
    );
    await expect(request("/api/stats")).rejects.toBeInstanceOf(ApiError);
    await expect(request("/api/stats")).rejects.toMatchObject({
      code: "invalid_response",
      status: 500,
    });
  });
});
