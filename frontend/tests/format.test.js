import { describe, expect, it } from "vitest";
import {
  number,
  duration,
  detailLink,
  resultLabel,
  position,
  timestamp,
} from "../src/utils/format.js";
import { radarOption, trendOption } from "../src/utils/charts.js";

describe("数据显示与图表口径", () => {
  it("缺失数字用占位符，真实零值仍显示零", () => {
    expect(number(null)).toBe("—");
    expect(number(undefined)).toBe("—");
    expect(number(0)).toBe("0");
    expect(duration(1835)).toBe("30:35");
    expect(duration(null)).toBe("—");
  });
  it("名称路由正确编码，胜负未知不会假装失败", () => {
    expect(detailLink("player", "A/B 中文")).toBe(
      "/player/A%2FB%20%E4%B8%AD%E6%96%87",
    );
    expect(resultLabel(null)).toBe("未记录");
    expect(resultLabel("1")).toBe("胜");
    expect(position("mid")).toBe("中单");
    expect(position("support")).toBe("辅助");
    expect(timestamp("2026-10-03T07:30:00Z")).toContain("15:30:00");
  });
  it("雷达只按指定轴映射百分位，tooltip展示原始指标与有效样本", () => {
    const axes = [
      { key: "kda", label: "KDA", unit: "" },
      { key: "part", label: "参团率", unit: "%" },
    ];
    const option = radarOption(axes, [
      {
        name: "选手",
        matches_count: 10,
        radar: [999],
        percentiles: { kda: 60, part: 75 },
        metrics: { kda: 3.2, part: 70 },
        metric_samples: { kda: 9, part: 10 },
      },
    ]);
    expect(option.series[0].data[0].value).toEqual([60, 75]);
    expect(option.tooltip.renderMode).toBe("richText");
    expect(option.tooltip.formatter({ dataIndex: 0 })).toContain(
      "KDA: 3.2 · 60 百分位 · n=9",
    );
  });
  it("月趋势中的缺失值不补零，不连接缺失段", () => {
    const option = trendOption([
      { month: "2024-01", kda: null, matches_count: 1 },
      { month: "2024-02", kda: 2.2, matches_count: 7 },
    ]);
    expect(option.series[0].data).toEqual([null, 2.2]);
    expect(option.series[0].connectNulls).toBe(false);
    expect(option.tooltip.formatter([{ dataIndex: 1 }])).toContain(
      "样本: 7 场",
    );
  });
});
