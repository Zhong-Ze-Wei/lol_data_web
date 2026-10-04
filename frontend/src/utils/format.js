export const positions = [
  { value: "a", label: "上单", short: "TOP" },
  { value: "b", label: "打野", short: "JGL" },
  { value: "c", label: "中单", short: "MID" },
  { value: "d", label: "射手", short: "BOT" },
  { value: "e", label: "辅助", short: "SUP" },
];

export function number(value, digits = 0) {
  if (
    value === null ||
    value === undefined ||
    value === "" ||
    !Number.isFinite(Number(value))
  )
    return "—";
  return Number(value).toLocaleString("zh-CN", {
    maximumFractionDigits: digits,
  });
}
export const percent = (value) =>
  value === null || value === undefined || value === ""
    ? "—"
    : `${number(value, 1)}%`;
export function duration(value) {
  if (
    value === null ||
    value === undefined ||
    value === "" ||
    !Number.isFinite(Number(value))
  )
    return "—";
  const seconds = Math.max(0, Math.round(Number(value)));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}
export const date = (value) =>
  value ? String(value).slice(0, 10) : "日期待确认";
export const timestamp = (value) =>
  new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Hong_Kong",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  })
    .format(new Date(value))
    .replaceAll("/", "-");
export function position(value) {
  const aliases = { top: "a", jungle: "b", mid: "c", adc: "d", support: "e" };
  return (
    positions.find((item) => item.value === (aliases[value] || value))?.label ||
    value ||
    "未记录"
  );
}
export const detailLink = (kind, name) =>
  `/${kind}/${encodeURIComponent(name)}`;
export function resultLabel(value) {
  if (value === 1 || value === "1" || value === true || value === "胜")
    return "胜";
  if (value === 0 || value === "0" || value === false || value === "负")
    return "负";
  return "未记录";
}
