<script setup>
import { computed, onScopeDispose, ref, shallowRef, watch } from "vue";
import { request } from "../services/api.js";
import { useResource } from "../composables/useResource.js";
import { number, timestamp } from "../utils/format.js";
import { historyLabel, stateCount } from "../utils/history.js";
import Icon from "./Icon.vue";

const { data, loading, error, reload } = useResource((signal) =>
  request("/api/sync/history", { signal }),
);
const latest = shallowRef(null);
const receivedAt = ref(performance.now());
const clock = ref(receivedAt.value);
watch(data, (value) => {
  if (value) {
    latest.value = value;
    receivedAt.value = performance.now();
    clock.value = receivedAt.value;
  }
});
const progress = computed(() => {
  const value = data.value || latest.value;
  if (!value?.worker) return value;
  const worker = value.worker;
  const age =
    worker.heartbeat_age_seconds + (clock.value - receivedAt.value) / 1000;
  return {
    ...value,
    worker: {
      ...worker,
      alive:
        worker.alive === true &&
        age >= 0 &&
        age <= worker.heartbeat_timeout_seconds,
    },
  };
});
const clockTimer = setInterval(() => {
  clock.value = performance.now();
}, 15000);
const refreshTimer = setInterval(reload, 30000);
onScopeDispose(() => {
  clearInterval(clockTimer);
  clearInterval(refreshTimer);
});
const runtimeLabel = computed(() => {
  const worker = progress.value?.worker;
  if (!worker) return "后台尚未报告运行状态";
  if (worker.alive) return "后台最近心跳正常";
  if (worker.status === "completed") return "本轮后台执行已结束";
  if (worker.status === "failed") return "后台执行遇到错误";
  if (worker.status === "stopped") return "后台执行已停止";
  return "未收到近期后台心跳，运行状态待确认";
});
const status = computed(() =>
  progress.value ? historyLabel(progress.value) : "读取历史补采进度…",
);
const metrics = computed(() => [
  {
    label: "赛事目录",
    value: progress.value?.counts?.catalog?.total,
    unit: "项",
  },
  {
    label: "系列对阵",
    value: progress.value?.counts?.series?.total,
    unit: "组",
  },
  {
    label: "目录内已核验",
    value: stateCount(progress.value?.counts?.results, "verified"),
    unit: "局",
  },
  {
    label: "待发布任务",
    value: progress.value?.pending_publication,
    unit: "项",
  },
]);
const knownStates = {
  queued: "待处理",
  running: "处理中",
  verified: "已核验",
  imported: "已导入",
  source_incomplete: "源缺项",
  failed: "失败",
  pending: "待发布",
  skipped: "已跳过",
};
const unmapped = computed(() =>
  Object.entries(progress.value?.counts?.known_unmapped_results || {}).map(
    ([key, count]) => ({ label: knownStates[key] || key, count }),
  ),
);
const fields = [
  ["tournaments", "目录赛事"],
  ["discovered_tournaments", "清单已发现"],
  ["series", "系列对阵"],
  ["discovered_results", "发现单局"],
  ["verified_results", "已核验单局"],
  ["complete_results", "完整战报"],
  ["source_incomplete", "源缺项"],
  ["pending_series", "待发布系列"],
  ["failed_tasks", "失败任务"],
];
</script>
<template>
  <section
    class="panel history-panel"
    aria-labelledby="history-progress-heading"
  >
    <header class="history-header">
      <h2 id="history-progress-heading"><Icon name="refresh" />历史补采进度</h2>
      <span
        class="history-state"
        :class="{
          active: !error && progress?.worker?.alive === true,
        }"
        >{{ error ? "历史补采进度暂不可用" : status }}</span
      >
      <button
        class="text-button small-text"
        :disabled="loading"
        @click="reload"
      >
        <Icon name="refresh" />刷新
      </button>
    </header>
    <template v-if="progress && !error">
      <dl class="history-metrics">
        <div v-for="metric in metrics" :key="metric.label">
          <dt>{{ metric.label }}</dt>
          <dd>
            {{ number(metric.value) }}<small>{{ metric.unit }}</small>
          </dd>
        </div>
      </dl>
      <div class="history-summary">
        <span title="已核验且有合法时长、10位选手、2支战队，且源数据无缺项。"
          >目录完整战报
          <strong>{{
            number(stateCount(progress.counts?.results, "complete"))
          }}</strong>
          局</span
        >
        <span
          >源缺项
          <strong>{{
            number(stateCount(progress.counts?.results, "source_incomplete"))
          }}</strong>
          局</span
        >
        <span
          >失败 <strong>{{ number(progress.failed_tasks) }}</strong> 项</span
        >
        <span
          >无确认日期
          <strong>{{ number(progress.counts?.series?.without_date) }}</strong>
          组</span
        >
        <span v-if="progress.exhausted_tasks > 0"
          >重试已耗尽
          {{ number(progress.exhausted_tasks) }} 项，需核查来源</span
        >
        <span
          v-if="progress.worker?.alive && progress.worker.current_batch != null"
          >当前第 {{ number(progress.worker.current_batch) }} 批</span
        >
        <span
          v-else-if="
            (progress.worker?.last_completed_batch ?? progress.worker?.batch) >
            0
          "
          >上次完成第
          {{
            number(
              progress.worker.last_completed_batch ?? progress.worker.batch,
            )
          }}
          批</span
        >
        <span>{{ runtimeLabel }}</span>
      </div>
      <details class="history-details">
        <summary>查看逐年进度与旧记录缺口</summary>
        <p class="muted small-text">
          {{
            progress.scope
          }}。逐年统计按已确认赛程，未知日期单列；目录内战报与未关联旧任务分别统计。完整战报需合法时长、10位选手与2支战队，且源数据无缺项。
        </p>
        <div v-if="progress.years?.length" class="table-scroll">
          <table>
            <thead>
              <tr>
                <th>赛程年份</th>
                <th v-for="[, label] in fields" :key="label" class="numeric">
                  {{ label }}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in progress.years" :key="row.year">
                <th>
                  {{ row.year === "unknown" ? "日期未确认" : `${row.year} 年` }}
                </th>
                <td v-for="[key] in fields" :key="key" class="numeric">
                  {{ number(row[key]) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="history-legacy">
          <span
            >未核验旧记录
            {{ number(progress.legacy?.unverified_matches) }} 局</span
          ><span
            >尚未关联目录的旧记录任务
            {{ number(progress.legacy?.known_unmapped_tasks) }} 项</span
          ><span v-for="item in unmapped" :key="item.label"
            >{{ item.label }} {{ number(item.count) }} 项</span
          >
        </div>
        <p v-if="progress.next_retry_at" class="muted small-text">
          下一次可重试时间：{{ timestamp(progress.next_retry_at) }}（香港时间）
        </p>
        <p class="muted small-text">
          <span v-if="progress.updated_at"
            >统计更新 {{ timestamp(progress.updated_at) }}（香港时间）</span
          ><span v-if="progress.schedule?.enabled">
            · 每日 {{ progress.schedule.time }} 继续补采</span
          >
        </p>
      </details>
    </template>
  </section>
</template>
