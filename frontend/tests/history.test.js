import { describe, expect, it } from "vitest";
import { historyLabel, stateCount } from "../src/utils/history.js";

describe("历史补采状态", () => {
  it("审计完成但仍有源站缺口时不宣称全部完整", () => {
    expect(
      historyLabel({
        snapshot_completed: true,
        complete_available: false,
        pending_publication: 8,
      }),
    ).toBe("当前补采已审计，仍有待发布或源缺项");
    expect(historyLabel({ complete_available: true })).toBe(
      "当前可用战报已补齐",
    );
  });
  it("区分正在运行、可继续处理和等待重试", () => {
    expect(historyLabel({ last_run: { status: "running" } })).toBe("正在补采");
    expect(historyLabel({ worker: { status: "continue" } })).toBe("正在补采");
    expect(historyLabel({ has_runnable_work: true })).toBe(
      "存在可继续补采的任务",
    );
    expect(historyLabel({ next_retry_at: "2026-10-04T00:00:00Z" })).toBe(
      "等待下一次重试",
    );
  });
  it("稀疏状态计数的未出现状态是零，未读取到计数字典保持未知", () => {
    expect(stateCount({ queued: 3 }, "failed")).toBe(0);
    expect(stateCount(undefined, "failed")).toBeUndefined();
  });
});
