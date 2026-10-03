import { describe, expect, it } from "vitest";
import {
  aiChart,
  evidenceItems,
  evidenceRange,
  formatCell,
  queryBody,
  resultColumns,
} from "../src/utils/ai.js";

const result = {
  data: [
    { player: "选手甲", avg_kda: 4.82, avg_kda_samples: 5 },
    { player: "选手乙", avg_kda: null, avg_kda_samples: 0 },
  ],
  columns: [
    { key: "player", label: "选手", type: "string" },
    { key: "avg_kda", label: "平均单局 KDA", type: "number", unit: "" },
  ],
  chart: {
    type: "bar",
    x: "player",
    series: [{ key: "avg_kda", label: "平均单局 KDA", unit: "" }],
  },
};

describe("可核查的 AI 结果", () => {
  it("区分用户时间筛选与真实赛程样本范围，不虚构历史日期", () => {
    expect(
      evidenceRange({
        requested_date_start: "2024-01-01",
        requested_date_end: "2024-12-31",
        date_start: "2024-03-01T12:00:00",
        date_end: "2024-05-02T10:00:00",
      }),
    ).toEqual({
      requested: "2024-01-01 至 2024-12-31",
      samples: "2024-03-01 至 2024-05-02",
    });
    expect(evidenceRange({ date_start: null, date_end: null })).toEqual({
      requested: "未限定比赛时间",
      samples: "真实比赛日期暂无样本",
    });
  });
  it("续问仅携带已有有效 plan，普通问题不添加空 context", () => {
    expect(queryBody("  查询选手  ", null)).toEqual({ prompt: "查询选手" });
    expect(queryBody("查询选手", {})).toEqual({ prompt: "查询选手" });
    const context = { plan: { entity: "players", position: "c" } };
    expect(queryBody("只看今年", context)).toEqual({
      prompt: "只看今年",
      context,
    });
  });
  it("中文列来自 DTO，缺失数字保持缺失，零仍显示零", () => {
    expect(resultColumns(result).map((column) => column.label)).toEqual([
      "选手",
      "平均单局 KDA",
    ]);
    expect(formatCell(null, { type: "number" })).toBe("—");
    expect(formatCell(undefined, { type: "number" })).toBe("—");
    expect(formatCell(0, { type: "number" })).toBe("0");
    expect(formatCell(4.8231, { type: "number" })).toBe("4.82");
  });
  it("图表保留缺失值，tooltip 说明指标样本", () => {
    const chart = aiChart(result);
    expect(chart.option.series[0].data).toEqual([4.82, null]);
    expect(chart.option.series[0].connectNulls).toBe(false);
    expect(chart.option.tooltip.renderMode).toBe("richText");
    expect(chart.option.tooltip.formatter([{ dataIndex: 0 }])).toContain(
      "指标样本: 5",
    );
    expect(chart.option.tooltip.formatter([{ dataIndex: 1 }])).toContain(
      "平均单局 KDA: —",
    );
  });
  it("仅接受受控图类型、数据列和同单位指标，不执行任意配置", () => {
    expect(
      aiChart({ ...result, chart: { ...result.chart, type: "custom" } }),
    ).toBeNull();
    expect(
      aiChart({ ...result, chart: { ...result.chart, x: "不存在的列" } }),
    ).toBeNull();
    expect(
      aiChart({
        ...result,
        columns: [
          ...result.columns,
          { key: "avg_kda_samples", type: "number" },
        ],
        chart: {
          ...result.chart,
          series: [
            ...result.chart.series,
            { key: "avg_kda_samples", label: "样本", unit: "场" },
          ],
        },
      }),
    ).toBeNull();
    expect(
      aiChart({ ...result, data: [{ player: "甲", avg_kda: null }] }),
    ).toBeNull();
  });
  it("较大结果限制图表点数并保留总数供界面说明", () => {
    const chart = aiChart({
      ...result,
      data: Array.from({ length: 80 }, (_, index) => ({
        player: `选手${index}`,
        avg_kda: index,
      })),
    });
    expect(chart.displayed).toBe(60);
    expect(chart.total).toBe(80);
  });
  it("质量证据保留真实零，不将未提供统计伪造为零", () => {
    expect(
      evidenceItems({ matches: 5, verified_matches: 0, unknown_results: null }),
    ).toEqual([
      { key: "matches", label: "比赛样本", value: "5", unit: "场" },
      { key: "verified_matches", label: "已核验", value: "0", unit: "场" },
    ]);
  });
});
