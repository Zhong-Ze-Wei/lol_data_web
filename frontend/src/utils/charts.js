import { number } from "./format.js";
export const colors = ["#1677ff", "#ff7d00", "#00a870", "#7b61d1"];
const textStyle = {
  color: "#4e5969",
  fontFamily: "Microsoft YaHei, sans-serif",
};

export function radarOption(axes, players) {
  return {
    color: colors,
    animation: false,
    legend: { bottom: 0, textStyle },
    tooltip: {
      backgroundColor: "#ffffff",
      borderColor: "#dce2ea",
      textStyle: { color: "#1d2129" },
      renderMode: "richText",
      formatter: (item) => {
        const player = players[item.dataIndex];
        return `${player.name} · ${player.matches_count} 场\n${axes.map((axis) => `${axis.label}: ${number(player.metrics[axis.key], 2)}${axis.unit || ""} · ${number(player.percentiles[axis.key])} 百分位 · n=${player.metric_samples[axis.key] || 0}`).join("\n")}`;
      },
    },
    radar: {
      center: ["50%", "45%"],
      radius: "64%",
      indicator: axes.map((axis) => ({ name: axis.label, max: 100 })),
      axisName: textStyle,
      splitNumber: 4,
      splitArea: { areaStyle: { color: ["#ffffff", "#f7f9fc"] } },
      splitLine: { lineStyle: { color: "#dbe2eb" } },
      axisLine: { lineStyle: { color: "#dbe2eb" } },
    },
    series: [
      {
        type: "radar",
        symbolSize: 5,
        lineStyle: { width: 2 },
        areaStyle: { opacity: 0.07 },
        data: players.map((player) => ({
          name: player.name,
          value: axes.map((axis) => player.percentiles[axis.key]),
        })),
      },
    ],
  };
}

export function trendOption(monthly, metric = "kda", label = "KDA") {
  return {
    color: colors,
    animation: false,
    tooltip: {
      backgroundColor: "#ffffff",
      borderColor: "#dce2ea",
      textStyle: { color: "#1d2129" },
      trigger: "axis",
      renderMode: "richText",
      formatter: (items) => {
        const row = monthly[items[0].dataIndex];
        return `${row.month}\n${label}: ${number(row[metric], 2)}\n样本: ${row.matches_count} 场`;
      },
    },
    grid: { top: 25, right: 25, bottom: 35, left: 55 },
    xAxis: {
      type: "category",
      data: monthly.map((item) => item.month),
      axisLabel: textStyle,
      axisLine: { lineStyle: { color: "#d4d9e1" } },
    },
    yAxis: {
      type: "value",
      axisLabel: textStyle,
      splitLine: { lineStyle: { color: "#edf0f4" } },
    },
    series: [
      {
        name: label,
        type: "line",
        connectNulls: false,
        symbolSize: 6,
        data: monthly.map((item) => item[metric]),
        lineStyle: { width: 2 },
      },
    ],
  };
}
