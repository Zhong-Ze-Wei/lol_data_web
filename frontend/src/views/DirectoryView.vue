<script setup>
import { computed, reactive, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { request } from "../services/api.js";
import { useResource } from "../composables/useResource.js";
import {
  positions,
  position,
  number,
  percent,
  date,
  duration,
  detailLink,
} from "../utils/format.js";
import ResourceState from "../components/ResourceState.vue";
import Pagination from "../components/Pagination.vue";

const props = defineProps({ kind: { type: String, required: true } });
const route = useRoute();
const router = useRouter();
const directories = {
  player: {
    title: "选手档案",
    english: "PLAYER ARCHIVE",
    description: "从每次出场，追踪选手的赛场表现。",
    endpoint: "/player/api/list",
    collection: "players",
    fields: [
      ["player_name", "选手名称"],
      ["team_name", "战队名称"],
      ["position", "位置"],
    ],
  },
  match: {
    title: "比赛记录",
    english: "MATCH ARCHIVE",
    description: "沿着队伍与日期，找到一场值得复盘的比赛。",
    endpoint: "/match/api/list",
    collection: "matches",
    fields: [
      ["team_name1", "战队一"],
      ["team_name2", "战队二"],
      ["start_date", "开始月份"],
      ["end_date", "结束月份"],
    ],
  },
  team: {
    title: "战队档案",
    english: "TEAM ARCHIVE",
    description: "查看已收录战队的出场记录与历史阵容。",
    endpoint: "/team/api/distinct",
    collection: "teams",
    fields: [["team_name", "战队名称"]],
  },
  hero: {
    title: "英雄数据",
    english: "CHAMPION ARCHIVE",
    description: "从实际选用样本，观察英雄的出场与表现。",
    endpoint: "/hero/api/list",
    collection: "heroes",
    fields: [
      ["hero_name", "英雄名称"],
      ["position", "位置"],
    ],
  },
};
const config = computed(() => directories[props.kind]);
const filters = reactive({});
watch(
  [() => props.kind, () => route.query],
  () => {
    for (const key of Object.keys(filters)) delete filters[key];
    for (const [key] of config.value.fields)
      filters[key] = String(route.query[key] || "");
  },
  { immediate: true },
);
const resource = useResource(
  (signal) => request(config.value.endpoint, { params: route.query, signal }),
  [() => props.kind, () => route.fullPath],
);
const rows = computed(
  () => resource.data.value?.[config.value.collection] || [],
);
function search() {
  const query = Object.fromEntries(
    Object.entries(filters)
      .map(([key, value]) => [key, value.trim()])
      .filter(([, value]) => value),
  );
  router.push({ path: `/${props.kind}`, query });
}
function reset() {
  router.push({ path: `/${props.kind}` });
}
function page(value) {
  router.push({ path: route.path, query: { ...route.query, page: value } });
}
</script>
<template>
  <header class="page-heading">
    <p class="eyebrow">{{ config.english }} / DATABASE</p>
    <h1>{{ config.title }}<span class="heading-rule"></span></h1>
    <p>{{ config.description }}</p>
  </header>
  <section class="panel">
    <form class="filter-form" @submit.prevent="search">
      <label v-for="[key, label] in config.fields" :key="key"
        >{{ label
        }}<select v-if="key === 'position'" v-model="filters[key]">
          <option value="">全部位置</option>
          <option
            v-for="item in positions"
            :key="item.value"
            :value="item.value"
          >
            {{ item.label }}
          </option></select
        ><input
          v-else
          v-model="filters[key]"
          :type="key.includes('date') ? 'month' : 'search'"
          :placeholder="key.includes('date') ? '' : `输入${label}`"
      /></label>
      <div class="filter-buttons">
        <button class="button small">筛选 ↗</button
        ><button class="button secondary small" type="button" @click="reset">
          重置
        </button>
      </div>
    </form>
    <p v-if="kind === 'match'" class="filter-note">
      日期筛选包含结束月份；历史记录日期来自源数据更新时间。
    </p>
    <ResourceState
      :loading="resource.loading.value"
      :error="resource.error.value"
      :empty="!rows.length"
      @retry="resource.reload"
      ><div class="table-scroll">
        <table v-if="kind === 'player'">
          <thead>
            <tr>
              <th>选手</th>
              <th>最近收录战队</th>
              <th>位置</th>
              <th class="numeric">出场样本</th>
              <th>最近记录日期</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in rows" :key="row.name">
              <td>
                <RouterLink
                  class="entity-name"
                  :to="detailLink('player', row.name)"
                  >{{ row.name }}</RouterLink
                >
              </td>
              <td>
                <RouterLink
                  v-if="row.team_name"
                  :to="detailLink('team', row.team_name)"
                  >{{ row.team_name }}</RouterLink
                ><span v-else>—</span>
              </td>
              <td>
                <span class="position-tag">{{ position(row.position) }}</span>
              </td>
              <td class="numeric">
                {{ number(row.appearance_count) }} <small>场</small>
              </td>
              <td class="muted">{{ date(row.latest_date) }}</td>
              <td>
                <RouterLink
                  class="row-arrow"
                  :to="detailLink('player', row.name)"
                  :aria-label="`查看 ${row.name}`"
                  >↗</RouterLink
                >
              </td>
            </tr>
          </tbody>
        </table>
        <table v-else-if="kind === 'match'">
          <thead>
            <tr>
              <th>记录日期</th>
              <th>蓝方</th>
              <th></th>
              <th>红方</th>
              <th>获胜队伍</th>
              <th class="numeric">比赛时长</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in rows" :key="row.match_id">
              <td class="muted">
                {{ date(row.date)
                }}<small class="block mono">#{{ row.match_id }}</small>
              </td>
              <td>
                <RouterLink :to="detailLink('team', row.blue_team_name)">{{
                  row.blue_team_name
                }}</RouterLink>
              </td>
              <td class="versus">VS</td>
              <td>
                <RouterLink :to="detailLink('team', row.red_team_name)">{{
                  row.red_team_name
                }}</RouterLink>
              </td>
              <td class="positive">{{ row.win_team_name || "未记录" }}</td>
              <td class="numeric">{{ duration(row.game_time) }}</td>
              <td>
                <RouterLink
                  class="row-arrow"
                  :to="detailLink('match', row.match_id)"
                  :aria-label="`查看比赛 ${row.match_id}`"
                  >↗</RouterLink
                >
              </td>
            </tr>
          </tbody>
        </table>
        <table v-else-if="kind === 'team'">
          <thead>
            <tr>
              <th>战队名称</th>
              <th class="numeric">出场样本</th>
              <th>数据入口</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in rows" :key="row.team_name">
              <td>
                <RouterLink
                  class="entity-name"
                  :to="detailLink('team', row.team_name)"
                  >{{ row.team_name }}</RouterLink
                >
              </td>
              <td class="numeric">
                {{ number(row.match_count) }} <small>场</small>
              </td>
              <td>
                <RouterLink
                  class="text-link"
                  :to="detailLink('team', row.team_name)"
                  >战绩与阵容 ↗</RouterLink
                >
              </td>
            </tr>
          </tbody>
        </table>
        <table v-else>
          <thead>
            <tr>
              <th>英雄</th>
              <th class="numeric">出场样本</th>
              <th class="numeric">胜率</th>
              <th>主要位置</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in rows" :key="row.hero_name">
              <td>
                <RouterLink
                  class="entity-name"
                  :to="detailLink('hero', row.hero_name)"
                  >{{ row.hero_name }}</RouterLink
                >
              </td>
              <td class="numeric">
                {{ number(row.matches_count) }} <small>场</small>
              </td>
              <td class="numeric">{{ percent(row.win_rate) }}</td>
              <td>{{ position(row.position) }}</td>
              <td>
                <RouterLink
                  class="row-arrow"
                  :to="detailLink('hero', row.hero_name)"
                  :aria-label="`查看 ${row.hero_name}`"
                  >↗</RouterLink
                >
              </td>
            </tr>
          </tbody>
        </table>
      </div></ResourceState
    ><Pagination :pagination="resource.data.value?.pagination" @page="page" />
  </section>
</template>
