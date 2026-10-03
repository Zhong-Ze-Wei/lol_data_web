<script setup>
import { computed, reactive, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { request } from "../services/api.js";
import { useResource } from "../composables/useResource.js";
import {
  positions,
  number,
  percent,
  duration,
  detailLink,
} from "../utils/format.js";
import { radarOption, colors } from "../utils/charts.js";
import ResourceState from "../components/ResourceState.vue";
import Pagination from "../components/Pagination.vue";
import Chart from "../components/Chart.vue";

const route = useRoute();
const router = useRouter();
const tab = computed(() => (route.query.tab === "teams" ? "teams" : "players"));
const filters = reactive({
  position: "a",
  min_matches: "5",
  date_from: "",
  date_to: "",
  team_names: "",
});
watch(
  () => route.query,
  () => {
    filters.position = String(route.query.position || "a");
    filters.min_matches = String(route.query.min_matches || "5");
    filters.date_from = String(route.query.date_from || "");
    filters.date_to = String(route.query.date_to || "");
    filters.team_names = String(route.query.team_names || "");
  },
  { immediate: true },
);
const cohortKey = computed(() =>
  [
    route.query.position || "a",
    route.query.min_matches || "5",
    route.query.date_from || "",
    route.query.date_to || "",
  ].join("|"),
);
const selected = ref([]);
watch(cohortKey, () => {
  selected.value = [];
});
const players = useResource(
  (signal) =>
    tab.value === "players"
      ? request("/api/analytics/players", {
          params: {
            ...route.query,
            position: route.query.position || "a",
            min_matches: route.query.min_matches || "5",
          },
          signal,
        })
      : Promise.resolve(null),
  [() => route.fullPath],
);
const teams = useResource(
  (signal) =>
    tab.value === "teams"
      ? request("/api/analytics/teams", { params: route.query, signal })
      : Promise.resolve(null),
  [() => route.fullPath],
);
watch(players.data, (data) => {
  if (data?.players.length && !selected.value.length)
    selected.value = data.players.slice(0, 2);
});
const availableAxes = computed(() =>
  (players.data.value?.axes || []).filter((axis) =>
    selected.value.every(
      (player) =>
        player.percentiles[axis.key] !== null &&
        player.percentiles[axis.key] !== undefined,
    ),
  ),
);
const radar = computed(() => radarOption(availableAxes.value, selected.value));
const omitted = computed(
  () => (players.data.value?.axes.length || 0) - availableAxes.value.length,
);
function selectPlayer(player) {
  const index = selected.value.findIndex(
    (item) => item.name === player.name && item.position === player.position,
  );
  if (index >= 0) selected.value = selected.value.filter((_, i) => i !== index);
  else if (selected.value.length < 4)
    selected.value = [...selected.value, player];
}
const isSelected = (player) =>
  selected.value.some(
    (item) => item.name === player.name && item.position === player.position,
  );
function switchTab(next) {
  router.push({
    path: "/analytics",
    query: { ...route.query, tab: next, page: undefined },
  });
}
function search() {
  const values =
    tab.value === "players"
      ? {
          position: filters.position,
          min_matches: filters.min_matches,
          date_from: filters.date_from,
          date_to: filters.date_to,
        }
      : {
          team_names: filters.team_names
            .split(/[,，]/)
            .map((value) => value.trim())
            .filter(Boolean)
            .join(","),
          date_from: filters.date_from,
          date_to: filters.date_to,
        };
  router.push({
    path: "/analytics",
    query: {
      tab: tab.value,
      ...Object.fromEntries(
        Object.entries(values).filter(([, value]) => value),
      ),
    },
  });
}
const teamChart = computed(() => {
  const rows = teams.data.value?.teams || [];
  return {
    animation: false,
    color: colors,
    tooltip: {
      trigger: "axis",
      renderMode: "richText",
      formatter: (items) => {
        const team = rows[items[0].dataIndex];
        return `${team.team_name}\n场均击杀: ${number(team.avg_kills, 2)}\n样本: ${team.matches_count} 场`;
      },
    },
    grid: { top: 20, right: 25, bottom: 35, left: 45 },
    xAxis: {
      type: "category",
      data: rows.map((row) => row.team_name),
      axisLabel: { color: "#4e5969" },
      axisLine: { lineStyle: { color: "#d4d9e1" } },
    },
    yAxis: {
      type: "value",
      axisLabel: { color: "#4e5969" },
      splitLine: { lineStyle: { color: "#edf0f4" } },
    },
    series: [
      {
        type: "bar",
        barMaxWidth: 45,
        data: rows.map((row, index) => ({
          value: row.avg_kills,
          itemStyle: { color: colors[index % colors.length] },
        })),
      },
    ],
  };
});
</script>
<template>
  <header class="page-heading">
    <h1>比较分析</h1>
    <p>先统一位置、日期和样本门槛，再阅读表现差异。</p>
  </header>
  <div class="analysis-tabs" aria-label="分析类型">
    <button
      :class="{ selected: tab === 'players' }"
      @click="switchTab('players')"
    >
      选手 · 五位置雷达</button
    ><button :class="{ selected: tab === 'teams' }" @click="switchTab('teams')">
      战队 · 战绩比较
    </button>
  </div>
  <section class="panel">
    <form class="filter-form" @submit.prevent="search">
      <template v-if="tab === 'players'"
        ><label
          >比较位置<select v-model="filters.position">
            <option
              v-for="item in positions"
              :key="item.value"
              :value="item.value"
            >
              {{ item.label }} / {{ item.short }}
            </option>
          </select></label
        ><label
          >最低出场场次<input
            v-model="filters.min_matches"
            type="number"
            min="1"
            max="1000000"
            required /></label></template
      ><label v-else class="wide-field"
        >战队名称<input
          v-model="filters.team_names"
          type="text"
          placeholder="如 T1, GEN，用逗号分隔"
          maxlength="300" /></label
      ><label>开始日期<input v-model="filters.date_from" type="date" /></label
      ><label
        >结束日期<input
          v-model="filters.date_to"
          type="date"
          :min="filters.date_from"
      /></label>
      <div class="filter-buttons">
        <button class="button small">应用筛选</button>
      </div>
    </form>
    <p class="filter-note">
      {{
        (tab === "players"
          ? players.data.value?.date_policy
          : teams.data.value?.date_policy) || "日期筛选仅包含已确认赛程。"
      }}分析范围仅覆盖已收录样本，胜率使用结果已知的比赛。
    </p>
  </section>
  <template v-if="tab === 'players'"
    ><ResourceState
      :loading="players.loading.value"
      :error="players.error.value"
      :empty="!players.data.value?.players.length"
      @retry="players.reload"
      ><div class="analysis-grid section-space">
        <section class="panel">
          <header class="panel-header">
            <div>
              <h2>赛场风格轮廓</h2>
            </div>
            <span class="tag"
              >{{ number(players.data.value.cohort_size) }} 位同位置选手</span
            >
          </header>
          <Chart
            v-if="selected.length && availableAxes.length >= 3"
            :option="radar"
            label="所选选手同位置指标百分位雷达图"
            :height="360"
          />
          <div v-else class="state-box">
            选择选手后展示雷达；至少需要 3 个共同有数据的指标。
          </div>
          <p class="chart-note">
            每条轴是同位置指标均值的百分位（0–100），并列取排名中点。承伤描述职责，不能与其他轴相加作为综合实力。<span
              v-if="omitted"
            >
              {{ omitted }} 个缺失指标未绘制。</span
            >
          </p>
        </section>
        <section class="panel">
          <header class="panel-header">
            <div>
              <h2>本次比较</h2>
            </div>
            <span class="tag">{{ selected.length }} / 4</span>
          </header>
          <div class="selected-players">
            <div v-for="(player, index) in selected" :key="player.name">
              <span
                class="player-dot"
                :style="{ background: colors[index] }"
              ></span
              ><RouterLink :to="detailLink('player', player.name)">{{
                player.name
              }}</RouterLink
              ><span class="muted">{{ number(player.matches_count) }} 场</span
              ><button
                class="text-button"
                @click="selectPlayer(player)"
                :aria-label="`移除 ${player.name}`"
              >
                ×
              </button>
            </div>
          </div>
          <p class="small-text muted">
            在下方勾选最多 4 位选手；翻页后仍保留本次比较。
          </p>
          <div v-if="selected.length" class="table-scroll compact-table">
            <table>
              <thead>
                <tr>
                  <th>原始指标</th>
                  <th
                    v-for="player in selected"
                    :key="player.name"
                    class="numeric"
                  >
                    {{ player.name }}
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="axis in players.data.value.axes" :key="axis.key">
                  <th>
                    {{ axis.label }}<small class="block">{{ axis.unit }}</small>
                  </th>
                  <td
                    v-for="player in selected"
                    :key="player.name"
                    class="numeric"
                  >
                    {{ number(player.metrics[axis.key], 2)
                    }}<small class="block"
                      >n={{ player.metric_samples[axis.key] }}</small
                    >
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </div>
      <section class="panel section-space">
        <header class="panel-header">
          <div>
            <h2>同位置样本</h2>
          </div>
          <span class="muted small-text">按出场样本排序</span>
        </header>
        <div class="table-scroll">
          <table>
            <thead>
              <tr>
                <th>比较</th>
                <th>选手</th>
                <th>最近收录战队</th>
                <th class="numeric">出场样本</th>
                <th class="numeric">胜率</th>
                <th class="numeric">KDA</th>
                <th class="numeric">分均经济</th>
                <th class="numeric">分均补刀</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="player in players.data.value.players"
                :key="`${player.name}-${player.position}`"
                :class="{ checked: isSelected(player) }"
              >
                <td>
                  <input
                    type="checkbox"
                    :checked="isSelected(player)"
                    :disabled="selected.length === 4 && !isSelected(player)"
                    :aria-label="`比较 ${player.name}`"
                    @change="selectPlayer(player)"
                  />
                </td>
                <td>
                  <RouterLink
                    class="entity-name"
                    :to="detailLink('player', player.name)"
                    >{{ player.name }}</RouterLink
                  >
                </td>
                <td>{{ player.team_name || "—" }}</td>
                <td class="numeric">{{ number(player.matches_count) }}</td>
                <td class="numeric">{{ percent(player.win_rate) }}</td>
                <td class="numeric">{{ number(player.metrics.kda, 2) }}</td>
                <td class="numeric">{{ number(player.metrics.money_M, 1) }}</td>
                <td class="numeric">{{ number(player.metrics.adc_m, 2) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <Pagination
          :pagination="players.data.value.pagination"
          @page="
            (page) =>
              router.push({ path: route.path, query: { ...route.query, page } })
          "
        /></section></ResourceState
  ></template>
  <template v-else
    ><ResourceState
      :loading="teams.loading.value"
      :error="teams.error.value"
      :empty="!teams.data.value?.teams.length"
      @retry="teams.reload"
      ><section class="panel section-space">
        <header class="panel-header">
          <div>
            <h2>战队样本比较</h2>
          </div>
          <span class="tag">{{ teams.data.value.teams.length }} 支战队</span>
        </header>
        <div class="table-scroll">
          <table>
            <thead>
              <tr>
                <th>战队</th>
                <th class="numeric">出场样本</th>
                <th class="numeric">胜率</th>
                <th class="numeric">场均击杀</th>
                <th class="numeric">场均死亡</th>
                <th class="numeric">场均经济</th>
                <th class="numeric">场均推塔</th>
                <th class="numeric">平均时长</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="team in teams.data.value.teams" :key="team.team_name">
                <td>
                  <RouterLink
                    class="entity-name"
                    :to="detailLink('team', team.team_name)"
                    >{{ team.team_name }}</RouterLink
                  >
                </td>
                <td class="numeric">{{ number(team.matches_count) }}</td>
                <td class="numeric">{{ percent(team.win_rate) }}</td>
                <td class="numeric">{{ number(team.avg_kills, 1) }}</td>
                <td class="numeric">{{ number(team.avg_deaths, 1) }}</td>
                <td class="numeric">{{ number(team.avg_money) }}</td>
                <td class="numeric">{{ number(team.avg_tower, 1) }}</td>
                <td class="numeric">{{ duration(team.avg_game_time) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
      <div class="analysis-grid section-space">
        <section class="panel">
          <header class="panel-header">
            <div>
              <h2>场均击杀</h2>
            </div>
          </header>
          <Chart :option="teamChart" label="所选战队场均击杀比较" />
          <p class="chart-note">
            悬停查看原始指标和样本场次；未收录结果不参与胜率计算。
          </p>
        </section>
        <section class="panel">
          <header class="panel-header">
            <div>
              <h2>直接交手</h2>
            </div>
          </header>
          <ResourceState
            :empty="!teams.data.value.head_to_head.length"
            empty-text="所选范围内没有收录直接交手。"
            ><div class="head-to-head">
              <div
                v-for="pair in teams.data.value.head_to_head"
                :key="`${pair.team_a}-${pair.team_b}`"
              >
                <div>
                  <strong>{{ pair.team_a }}</strong
                  ><span class="head-score"
                    >{{ pair.team_a_wins }} : {{ pair.team_b_wins }}</span
                  ><strong>{{ pair.team_b }}</strong>
                </div>
                <p class="muted small-text">
                  {{ pair.matches_count }} 局比赛<span
                    v-if="pair.unknown_results"
                  >
                    · {{ pair.unknown_results }} 局结果未记录</span
                  >
                </p>
              </div>
            </div></ResourceState
          >
          <p class="chart-note">按单局比赛统计，不把 BO 系列赛合并计数。</p>
        </section>
      </div></ResourceState
    ></template
  >
</template>
