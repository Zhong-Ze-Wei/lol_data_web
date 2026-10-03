<script setup>
defineProps({ name: { type: String, default: "match" } });
const paths = {
  home: "M3 10 12 3l9 7v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1Z",
  match:
    "M8 3h8v5a4 4 0 0 1-8 0ZM8 5H4v2a4 4 0 0 0 4 4m8-6h4v2a4 4 0 0 1-4 4m-4 1v6m-5 3h10m-8-3h6v3",
  player:
    "M16 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0ZM4 21v-3a6 6 0 0 1 6-6h4a6 6 0 0 1 6 6v3",
  team: "M15 7a3 3 0 1 1-6 0 3 3 0 0 1 6 0ZM5 21v-3a5 5 0 0 1 5-5h4a5 5 0 0 1 5 5v3M5 5a3 3 0 0 0 0 6m14-6a3 3 0 0 1 0 6M2 19v-2a4 4 0 0 1 3-4m17 6v-2a4 4 0 0 0-3-4",
  hero: "M12 3 3 7v6c0 4 9 8 9 8s9-4 9-8V7ZM8 12l3 3 5-6",
  chart: "M4 3v18h17M8 16v-5m5 5V6m5 10V9",
  search: "M17 10a7 7 0 1 1-14 0 7 7 0 0 1 14 0Zm-2 5 6 6",
  refresh:
    "M20 7v5h-5M4 17v-5h5M5 8a8 8 0 0 1 13-3l2 2M4 17l2 2a8 8 0 0 0 13-3",
  arrow: "M4 12h16m-6-6 6 6-6 6",
  ai: "M5 5h14v12H8l-3 4ZM8 9h8m-8 4h5",
  check: "m5 12 4 4L19 6",
};
</script>
<template>
  <svg
    class="icon"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.7"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <path :d="paths[name] || paths.match" />
  </svg>
</template>
