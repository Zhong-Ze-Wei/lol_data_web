import { describe, expect, it } from "vitest";
import { renderAnswer } from "../src/utils/markdown.js";

describe("AI 回答安全渲染", () => {
  it("保留 Markdown 表格、空表格单元格和中文内容", () => {
    const html = renderAnswer(
      "| 选手 | KDA |\n| --- | --- |\n| Faker | 3.4 |\n| 中文 | |",
    );
    expect(html).toContain("<table>");
    expect(html).toContain("<td>Faker</td>");
    expect(html).toContain("<td></td>");
  });
  it("删除脚本、事件处理程序、危险链接和图片", () => {
    const html = renderAnswer(
      '<script>alert(1)</script><img src=x onerror=alert(2)><a href="javascript:alert(3)" onclick="alert(4)">打开</a>\n\n[危险](javascript:alert(5))',
    );
    expect(html).not.toMatch(/<script|<img|onerror|onclick|href="javascript:/i);
  });
  it("保留站内选手链接与常规 HTTPS 链接", () => {
    const html = renderAnswer(
      "[选手](/player/Faker) [来源](https://example.com/data)",
    );
    expect(html).toContain('href="/player/Faker"');
    expect(html).toContain('href="https://example.com/data"');
  });
});
