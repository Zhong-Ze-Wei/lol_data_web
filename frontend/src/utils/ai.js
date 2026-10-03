import { number, date } from "./format.js";
import { colors } from "./charts.js";

export const aiStatuses = {
  ok: { label: "分析完成", className: "complete" },
  empty: { label: "没有匹配数据", className: "empty" },
  needs_clarification: { label: "需要补充条件", className: "clarify" },
  unsupported: { label: "当前无法分析", className: "unsupported" },
};

export function queryBody(prompt, context) {
  return context?.plan
    ? { prompt: prompt.trim(), context }
    : { prompt: prompt.trim() };
}

export function resultColumns(result) {
  const keys = Object.keys(result.data?.[0] || {});
  return result.columns?.length
    ? result.columns.filter((column) => keys.includes(column.key))
    : keys.map((key) => ({ key, label: key }));
}

export function formatCell(value, column = {}) {
  if (value === null || value === undefined || value === "") return "—";
  if (column.type === "number") return number(value, 2);
  if (column.type === "date") return String(value).slice(0, 10);
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

export function evidenceItems(evidence = {}) {
  const fields = [
    ["matches", "比赛样本", "场"],
    ["rows", "统计记录", "条"],
    ["verified_matches", "已核验", "场"],
    ["unverified_matches", "未核验", "场"],
    ["known_results", "胜负已知记录", "条"],
    ["unknown_results", "胜负未记录", "条"],
  ];
  return fields
    .filter(([key]) => evidence[key] !== null && evidence[key] !== undefined)
    .map(([key, label, unit]) => ({
      key,
      label,
      value: number(evidence[key]),
      unit,
    }));
}

export function evidenceRange(evidence = {}) {
  const requested =
    evidence.requested_date_start || evidence.requested_date_end
      ? `${evidence.requested_date_start ? date(evidence.requested_date_start) : "不限开始日期"} 至 ${evidence.requested_date_end ? date(evidence.requested_date_end) : "不限结束日期"}`
      : "未限定比赛时间";
  const samples =
    evidence.date_start || evidence.date_end
      ? `${evidence.date_start ? date(evidence.date_start) : "开始日期未记录"} 至 ${evidence.date_end ? date(evidence.date_end) : "结束日期未记录"}`
      : "真实比赛日期暂无样本";
  return { requested, samples };
}

export function aiChart(result) {
  const spec = result.chart;
  const columns = resultColumns(result);
  const rows = result.data || [];
  if (!spec || !["bar", "line"].includes(spec.type) || !rows.length)
    return null;
  const xColumn = columns.find((column) => column.key === spec.x);
  const series = (spec.series || []).filter((item) =>
    columns.some(
      (column) => column.key === item.key && column.type === "number",
    ),
  );
  if (
    !xColumn ||
    !series.length ||
    new Set(series.map((item) => item.unit || "")).size > 1
  )
    return null;
  const visible = rows.slice(0, 60);
  if (
    !series.some((item) =>
      visible.some(
        (row) =>
          typeof row[item.key] === "number" && Number.isFinite(row[item.key]),
      ),
    )
  )
    return null;
  const label = (item) => `${item.label}${item.unit ? `（${item.unit}）` : ""}`;
  return {
    displayed: visible.length,
    total: rows.length,
    option: {
      animation: false,
      color: colors,
      legend: { top: 0, textStyle: { color: "#4e5969" } },
      grid: { top: 48, left: 60, right: 24, bottom: 65 },
      tooltip: {
        trigger: "axis",
        renderMode: "richText",
        backgroundColor: "#fff",
        borderColor: "#dbe2eb",
        textStyle: { color: "#1d2129" },
        formatter: (items) => {
          const row = visible[items[0].dataIndex];
          const lines = [formatCell(row[spec.x], xColumn)];
          for (const item of series) {
            const column = columns.find((column) => column.key === item.key);
            lines.push(`${label(item)}: ${formatCell(row[item.key], column)}`);
            const samples = row[`${item.key}_samples`] ?? row.sample_size;
            if (samples !== null && samples !== undefined)
              lines.push(`指标样本: ${number(samples)}`);
          }
          return lines.join("\n");
        },
      },
      xAxis: {
        type: "category",
        data: visible.map((row) => formatCell(row[spec.x], xColumn)),
        axisLabel: {
          color: "#4e5969",
          hideOverlap: true,
          rotate: visible.length > 8 ? 30 : 0,
        },
        axisLine: { lineStyle: { color: "#d4d9e1" } },
        axisTick: { show: false },
      },
      yAxis: {
        type: "value",
        name: series[0].unit || "",
        nameTextStyle: { color: "#4e5969" },
        axisLabel: { color: "#4e5969" },
        splitLine: { lineStyle: { color: "#edf0f4" } },
      },
      series: series.map((item) => ({
        name: label(item),
        type: spec.type,
        barMaxWidth: 42,
        connectNulls: false,
        data: visible.map((row) =>
          typeof row[item.key] === "number" && Number.isFinite(row[item.key])
            ? row[item.key]
            : null,
        ),
      })),
    },
  };
}
