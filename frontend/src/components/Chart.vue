<script setup>
import { onMounted, onBeforeUnmount, ref, watch } from "vue";
import { init, use } from "echarts/core";
import { RadarChart, LineChart, BarChart } from "echarts/charts";
import {
  TooltipComponent,
  LegendComponent,
  GridComponent,
  RadarComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";

use([
  RadarChart,
  LineChart,
  BarChart,
  TooltipComponent,
  LegendComponent,
  GridComponent,
  RadarComponent,
  CanvasRenderer,
]);
const props = defineProps({
  option: { type: Object, required: true },
  label: { type: String, required: true },
  height: { type: Number, default: 340 },
});
const element = ref(null);
let chart;
let observer;
onMounted(() => {
  chart = init(element.value, null, { renderer: "canvas" });
  chart.setOption(props.option);
  observer = new ResizeObserver(() => chart.resize());
  observer.observe(element.value);
});
watch(
  () => props.option,
  (option) => chart?.setOption(option, true),
  { deep: true },
);
onBeforeUnmount(() => {
  observer?.disconnect();
  chart?.dispose();
});
</script>
<template>
  <div
    ref="element"
    class="chart"
    role="img"
    :aria-label="label"
    :style="{ height: `${height}px` }"
  ></div>
</template>
