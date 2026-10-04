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
import Icon from "../components/Icon.vue";
import MatchStatus from "../components/MatchStatus.vue";

const props = defineProps({ kind: { type: String, required: true } });
const route = useRoute();
const router = useRouter();
const directories = {
  player: {
    title: "选手档案",
    description: "寻找一位选手，从已收录的比赛认识他的赛场表现。",
    endpoint: "/player/api/list",
    collection: "players",
    unit: "位选手",
    fields: [
      ["player_name", "选手名称", "搜索选手名称"],
      ["team_name", "来源战队", "输入战队名称"],
    ],
    note: "出场样本来自已收录比赛，不等于完整职业生涯。",
    help: "战队与位置来自最近收录出场。选择「位置待确认」可查看尚无可靠位置的选手；最近赛程仅显示已确认比赛日期。",
  },
  match: {
    title: "比赛记录",
    description: "按赛事、队伍或单局编号，找到一场值得复盘的比赛。",
    endpoint: "/match/api/list",
    collection: "matches",
    unit: "场比赛",
    fields: [
      ["query", "搜索比赛", "队伍、赛事或单局编号"],
      ["tournament_name", "赛事名称", "输入真实赛事关键词"],
      ["team_name1", "战队一", "输入战队名称"],
      ["team_name2", "战队二", "输入另一支战队"],
      ["date_from", "开始日期", "YYYY-MM-DD / YYYY-MM"],
      ["date_to", "结束日期", "YYYY-MM-DD / YYYY-MM"],
    ],
    note: "日期筛选仅包含已确认赛程，包含结束日或结束月份。",
    help: "赛事按名称关键词查找，队伍筛选可组合使用。未筛日期时保留日期待确认的历史记录；已核验战报仍可能缺少时长或部分指标。",
  },
  team: {
    title: "战队档案",
    description: "从一支战队出发，查看比赛记录与历史阵容。",
    endpoint: "/team/api/distinct",
    collection: "teams",
    unit: "支战队",
    fields: [["team_name", "战队名称", "搜索战队名称"]],
    note: "按来源战队名称收录，出场样本以当前记录为准。",
    help: "进入战队档案可查看已收录战绩和阵容。同一组织的不同来源名称保留各自记录，不据此推断转会或更名。",
  },
  hero: {
    title: "英雄数据",
    description: "从实际选用样本，观察英雄的出场与表现。",
    endpoint: "/hero/api/list",
    collection: "heroes",
    unit: "个英雄",
    fields: [["hero_name", "英雄名称", "搜索英雄名称"]],
    note: "胜率仅以胜负已确认的选用样本计算。",
    help: "位置筛选对应实际出场位置，主要位置来自已收录样本。胜负或指标缺失的记录不作为零值计算。",
  },
};
const config = computed(() => directories[props.kind]);
const filters = reactive({});
const selectedDates = computed(() => {
  const modern = "date_from" in route.query || "date_to" in route.query;
  return {
    start: String(route.query[modern ? "date_from" : "start_date"] || ""),
    end: String(route.query[modern ? "date_to" : "end_date"] || ""),
  };
});
const positionOptions = computed(() => [
  { value: "", label: "全部位置" },
  ...positions,
  ...(props.kind === "player"
    ? [{ value: "unknown", label: "位置待确认" }]
    : []),
]);
watch(
  [() => props.kind, () => route.query],
  () => {
    for (const key of Object.keys(filters)) delete filters[key];
    for (const [key] of config.value.fields)
      filters[key] = String(route.query[key] || "");
    if (props.kind === "match") {
      filters.date_from = selectedDates.value.start;
      filters.date_to = selectedDates.value.end;
    }
    if (props.kind === "player" || props.kind === "hero")
      filters.position = String(route.query.position || "");
    if (props.kind === "player")
      filters.sort = String(route.query.sort || "appearance_count");
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
const featured = computed(() => rows.value[0]);
const featuredName = computed(() => {
  const row = featured.value;
  if (!row) return "";
  return props.kind === "player"
    ? row.name
    : props.kind === "team"
      ? row.team_name
      : props.kind === "hero"
        ? row.hero_name
        : `比赛 #${row.match_id}`;
});
const featuredLink = computed(() =>
  detailLink(
    props.kind,
    props.kind === "match" ? featured.value?.match_id : featuredName.value,
  ),
);
const dateRange = computed(() => {
  const { start, end } = selectedDates.value;
  return start || end
    ? `${start || "最早赛程"} 至 ${end || "最新赛程"}`
    : "全部日期";
});
function search() {
  const query = Object.fromEntries(
    Object.entries(filters)
      .map(([key, value]) => [key, value.trim()])
      .filter(([, value]) => value),
  );
  if (route.query.per_page) query.per_page = route.query.per_page;
  router.push({ path: `/${props.kind}`, query });
}
function selectPosition(value) {
  filters.position = value;
  search();
}
function reset() {
  router.push({ path: `/${props.kind}` });
}
function page(value) {
  router.push({ path: route.path, query: { ...route.query, page: value } });
}
function initials(name) {
  return String(name || "").slice(0, 2);
}
</script>
<template>
  <header class="page-heading">
    <h1>{{ config.title }}</h1>
    <p>{{ config.description }}</p>
  </header>
  <div class="directory-layout">
    <section class="panel directory-main" :aria-label="config.title">
      <form class="filter-form directory-search" @submit.prevent="search">
        <label
          v-for="[key, label, placeholder] in config.fields"
          :key="key"
          :class="{ 'wide-field': key === 'query' }"
        >
          {{ label
          }}<input
            v-model="filters[key]"
            :name="key"
            :type="key.includes('date') ? 'text' : 'search'"
            :placeholder="placeholder"
          />
        </label>
        <div class="filter-buttons">
          <button class="button small" type="submit">
            <Icon name="search" />查询
          </button>
          <button class="button secondary small" type="button" @click="reset">
            重置
          </button>
        </div>
      </form>
      <div v-if="kind === 'player' || kind === 'hero'" class="directory-tools">
        <div class="position-filters" role="group" aria-label="位置筛选">
          <button
            v-for="item in positionOptions"
            :key="item.value"
            type="button"
            :aria-pressed="filters.position === item.value"
            :class="{ selected: filters.position === item.value }"
            @click="selectPosition(item.value)"
          >
            {{ item.label }}
          </button>
        </div>
        <label v-if="kind === 'player'" class="sort-control"
          >排序
          <select v-model="filters.sort" name="sort" @change="search">
            <option value="appearance_count">出场样本最多</option>
            <option value="latest_match_date">最近确认赛程</option>
            <option value="name">选手名称 A–Z</option>
          </select>
        </label>
      </div>
      <div class="results-header">
        <div>
          <strong>查询结果</strong
          ><span v-if="resource.data.value">
            共 {{ number(resource.data.value.pagination.total) }}
            {{ config.unit }}</span
          >
        </div>
        <span v-if="kind === 'match'">{{ dateRange }}</span>
      </div>
      <ResourceState
        :loading="resource.loading.value"
        :error="resource.error.value"
        :empty="!rows.length"
        @retry="resource.reload"
      >
        <div class="table-scroll">
          <table v-if="kind === 'player'" class="player-directory">
            <thead>
              <tr>
                <th>选手</th>
                <th>最近收录战队</th>
                <th>位置</th>
                <th class="numeric">出场样本</th>
                <th>最近确认赛程</th>
                <th>档案</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in rows" :key="row.name">
                <td>
                  <RouterLink
                    class="entity-name directory-identity"
                    :to="detailLink('player', row.name)"
                  >
                    <span class="directory-avatar" aria-hidden="true"
                      ><img
                        v-if="row.pic"
                        :src="row.pic"
                        alt=""
                        loading="lazy"
                      /><span v-else>{{ initials(row.name) }}</span></span
                    >{{ row.name }}
                  </RouterLink>
                </td>
                <td>
                  <RouterLink
                    v-if="row.team_name"
                    :to="detailLink('team', row.team_name)"
                    >{{ row.team_name }}</RouterLink
                  ><span v-else class="muted">未记录</span>
                </td>
                <td>
                  <span class="position-tag">{{ position(row.position) }}</span>
                </td>
                <td class="numeric">{{ number(row.appearance_count) }}</td>
                <td class="muted">{{ date(row.latest_match_date) }}</td>
                <td>
                  <RouterLink
                    class="text-link"
                    :to="detailLink('player', row.name)"
                    :aria-label="`查看 ${row.name} 档案`"
                    >查看 <span aria-hidden="true">›</span></RouterLink
                  >
                </td>
              </tr>
            </tbody>
          </table>
          <table v-else-if="kind === 'match'" class="match-table">
            <thead>
              <tr>
                <th>日期 / 赛事</th>
                <th>对阵双方</th>
                <th>获胜战队</th>
                <th class="numeric">时长</th>
                <th>数据状态</th>
                <th>战报</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in rows" :key="row.match_id">
                <td class="match-event">
                  <span>{{ date(row.date) }}</span
                  ><small v-if="row.tournament_name" class="block muted">{{
                    row.tournament_name
                  }}</small
                  ><small class="block muted">#{{ row.match_id }}</small>
                </td>
                <td>
                  <div class="matchup-cell">
                    <template
                      v-for="(name, index) in [
                        row.blue_team_name,
                        row.red_team_name,
                      ]"
                      :key="index"
                    >
                      <span v-if="index" class="versus">VS</span>
                      <RouterLink
                        v-if="name"
                        :to="detailLink('team', name)"
                        class="team-in-row"
                      >
                        <span class="team-avatar blue-avatar">{{
                          initials(name)
                        }}</span
                        ><strong>{{ name }}</strong>
                        <span
                          v-if="row.win_team_name === name"
                          class="win-label"
                          >胜</span
                        ><span v-else-if="row.win_team_name" class="lose-label"
                          >负</span
                        > </RouterLink
                      ><span v-else class="muted">队伍待确认</span>
                    </template>
                  </div>
                </td>
                <td>
                  <span v-if="row.win_team_name" class="winner-name">{{
                    row.win_team_name
                  }}</span
                  ><span v-else class="muted">待确认</span>
                </td>
                <td class="numeric">
                  {{
                    row.game_time == null ? "未记录" : duration(row.game_time)
                  }}
                </td>
                <td>
                  <MatchStatus :verified="row.verified" /><small
                    v-if="row.source === 'scoregg_metadata'"
                    class="block muted"
                    >基础战报</small
                  >
                </td>
                <td>
                  <RouterLink
                    class="text-link"
                    :to="detailLink('match', row.match_id)"
                    :aria-label="`查看比赛 ${row.match_id}`"
                    >查看 <span aria-hidden="true">›</span></RouterLink
                  >
                </td>
              </tr>
            </tbody>
          </table>
          <table v-else-if="kind === 'team'">
            <thead>
              <tr>
                <th>战队</th>
                <th class="numeric">出场样本</th>
                <th>档案</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in rows" :key="row.team_name">
                <td>
                  <RouterLink
                    class="entity-name directory-identity"
                    :to="detailLink('team', row.team_name)"
                    ><span class="directory-avatar" aria-hidden="true">{{
                      initials(row.team_name)
                    }}</span
                    >{{ row.team_name }}</RouterLink
                  >
                </td>
                <td class="numeric">{{ number(row.match_count) }}</td>
                <td>
                  <RouterLink
                    class="text-link"
                    :to="detailLink('team', row.team_name)"
                    >战绩与阵容 <span aria-hidden="true">›</span></RouterLink
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
                <th>档案</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in rows" :key="row.hero_name">
                <td>
                  <RouterLink
                    class="entity-name directory-identity"
                    :to="detailLink('hero', row.hero_name)"
                  >
                    <span class="directory-avatar" aria-hidden="true"
                      ><img
                        v-if="row.pic"
                        :src="row.pic"
                        alt=""
                        loading="lazy"
                      /><span v-else>{{ initials(row.hero_name) }}</span></span
                    >{{ row.hero_name }}</RouterLink
                  >
                </td>
                <td class="numeric">{{ number(row.matches_count) }}</td>
                <td class="numeric">{{ percent(row.win_rate) }}</td>
                <td>
                  <span class="position-tag">{{ position(row.position) }}</span>
                </td>
                <td>
                  <RouterLink
                    class="text-link"
                    :to="detailLink('hero', row.hero_name)"
                    :aria-label="`查看 ${row.hero_name} 档案`"
                    >查看 <span aria-hidden="true">›</span></RouterLink
                  >
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </ResourceState>
      <Pagination :pagination="resource.data.value?.pagination" @page="page" />
      <p class="directory-note">{{ config.note }}</p>
    </section>
    <aside class="directory-sidebar" aria-label="档案与筛选说明">
      <section v-if="featured" class="panel directory-spotlight">
        <div class="directory-section-heading">
          <h2>{{ kind === "match" ? "战报速览" : "档案速览" }}</h2>
          <span>本页首条</span>
        </div>
        <RouterLink class="spotlight-name" :to="featuredLink">
          <span
            v-if="kind !== 'match'"
            class="directory-avatar spotlight-avatar"
            aria-hidden="true"
            ><img v-if="featured.pic" :src="featured.pic" alt="" /><span
              v-else
              >{{ initials(featuredName) }}</span
            ></span
          >
          <strong>{{ featuredName }}</strong>
        </RouterLink>
        <dl v-if="kind === 'player'" class="archive-facts">
          <div>
            <dt>来源战队</dt>
            <dd>{{ featured.team_name || "未记录" }}</dd>
          </div>
          <div>
            <dt>位置</dt>
            <dd>{{ position(featured.position) }}</dd>
          </div>
          <div>
            <dt>出场样本</dt>
            <dd>{{ number(featured.appearance_count) }} 场</dd>
          </div>
          <div>
            <dt>最近确认赛程</dt>
            <dd>{{ date(featured.latest_match_date) }}</dd>
          </div>
        </dl>
        <dl v-else-if="kind === 'match'" class="archive-facts">
          <div>
            <dt>赛事</dt>
            <dd>{{ featured.tournament_name || "赛事待确认" }}</dd>
          </div>
          <div>
            <dt>赛程</dt>
            <dd>{{ date(featured.date) }}</dd>
          </div>
          <div>
            <dt>对阵</dt>
            <dd>
              {{ featured.blue_team_name || "队伍待确认" }} /
              {{ featured.red_team_name || "队伍待确认" }}
            </dd>
          </div>
        </dl>
        <dl v-else-if="kind === 'hero'" class="archive-facts">
          <div>
            <dt>出场样本</dt>
            <dd>{{ number(featured.matches_count) }} 场</dd>
          </div>
          <div>
            <dt>胜率</dt>
            <dd>{{ percent(featured.win_rate) }}</dd>
          </div>
          <div>
            <dt>主要位置</dt>
            <dd>{{ position(featured.position) }}</dd>
          </div>
        </dl>
        <dl v-else class="archive-facts">
          <div>
            <dt>出场样本</dt>
            <dd>{{ number(featured.match_count) }} 场</dd>
          </div>
        </dl>
        <RouterLink class="spotlight-link" :to="featuredLink"
          >{{ kind === "match" ? "查看这场比赛" : "进入档案"
          }}<Icon name="arrow"
        /></RouterLink>
      </section>
      <section class="panel directory-help">
        <div class="directory-section-heading">
          <h2>查阅提示</h2>
          <Icon name="search" />
        </div>
        <p>{{ config.help }}</p>
        <div class="help-rule">
          <span class="help-dot"></span
          ><span>筛选与分页覆盖全部已收录记录。</span>
        </div>
        <div class="help-rule">
          <span class="help-dot"></span
          ><span>缺失数据保留未知，待来源补齐。</span>
        </div>
        <RouterLink class="text-link" to="/analytics"
          >比较选手表现 <span aria-hidden="true">›</span></RouterLink
        >
      </section>
    </aside>
  </div>
</template>

<style scoped>
.directory-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 264px;
  gap: 22px;
  align-items: start;
}
.directory-main,
.directory-sidebar {
  min-width: 0;
}
.directory-main {
  padding: 22px;
}
.directory-search {
  gap: 12px;
}
.directory-search label {
  min-width: 130px;
}
.directory-search input {
  min-width: 0;
  width: 100%;
}
.directory-tools {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 0 5px;
}
.position-filters {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}
.position-filters button {
  padding: 6px 9px;
  border: 1px solid transparent;
  background: transparent;
  color: #65758a;
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}
.position-filters button:hover {
  background: #f0f5fb;
  color: #1763b8;
}
.position-filters button.selected {
  border-color: #d8e6f6;
  background: #edf5ff;
  color: #1763b8;
  font-weight: 600;
}
.sort-control {
  display: flex;
  align-items: center;
  gap: 7px;
  color: #65758a;
  font-size: 12px;
}
.sort-control select {
  width: auto;
  max-width: 100%;
  padding: 7px 9px;
  font-size: 12px;
}
.directory-main th,
.directory-main td {
  padding: 11px 10px;
}
.directory-main th {
  background: #f4f7fb;
  color: #566981;
}
.directory-identity {
  display: inline-flex;
  align-items: center;
  gap: 11px;
}
.directory-avatar {
  display: inline-flex;
  width: 38px;
  height: 42px;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  background: #edf3fa;
  color: #1763b8;
  font-size: 12px;
  font-weight: 700;
}
.directory-avatar img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.directory-main .matchup-cell {
  gap: 10px;
  min-width: 245px;
}
.directory-main .team-in-row {
  min-width: 80px;
}
.match-event {
  min-width: 150px;
  max-width: 230px;
  white-space: normal;
}
.match-event small {
  line-height: 1.6;
  overflow-wrap: anywhere;
}
.directory-note {
  margin: 18px 0 0;
  color: #7b8798;
  font-size: 11px;
  line-height: 1.7;
}
.directory-sidebar {
  display: grid;
  gap: 18px;
}
.directory-sidebar .panel {
  padding: 20px;
}
.directory-section-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding-bottom: 14px;
  border-bottom: 1px solid #e5ebf2;
}
.directory-section-heading h2 {
  margin: 0;
  color: #153656;
  font-size: 15px;
}
.directory-section-heading > span {
  color: #8a96a6;
  font-size: 11px;
}
.directory-section-heading .icon {
  width: 16px;
  color: #8a96a6;
}
.spotlight-name {
  display: flex;
  align-items: center;
  gap: 12px;
  padding-top: 19px;
  color: #12375c;
  overflow-wrap: anywhere;
}
.spotlight-name strong {
  min-width: 0;
  font-size: 22px;
  line-height: 1.4;
}
.spotlight-avatar {
  width: 48px;
  height: 54px;
}
.archive-facts {
  display: grid;
  gap: 12px;
  margin: 19px 0;
  font-size: 12px;
}
.archive-facts > div {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: start;
  gap: 12px;
}
.archive-facts dt {
  color: #8190a2;
}
.archive-facts dd {
  margin: 0;
  color: #314a66;
  text-align: right;
  overflow-wrap: anywhere;
}
.spotlight-link {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding-top: 15px;
  border-top: 1px solid #e5ebf2;
  color: #1763b8;
  font-size: 12px;
}
.spotlight-link .icon {
  width: 15px;
}
.directory-help p {
  margin: 16px 0;
  color: #738195;
  font-size: 12px;
  line-height: 1.9;
}
.help-rule {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin: 11px 0;
  color: #738195;
  font-size: 11px;
  line-height: 1.7;
}
.help-dot {
  width: 4px;
  height: 4px;
  flex: 0 0 auto;
  border-radius: 50%;
  background: #7399c4;
}
.directory-help > .text-link {
  display: inline-block;
  margin-top: 12px;
  font-size: 12px;
}
@media (max-width: 1100px) {
  .directory-layout {
    grid-template-columns: minmax(0, 1fr);
  }
  .directory-sidebar {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
@media (max-width: 600px) {
  .directory-main {
    padding: 16px;
  }
  .directory-search label,
  .directory-search .wide-field {
    flex-basis: 100%;
    min-width: 0;
  }
  .directory-tools {
    gap: 14px;
  }
  .sort-control {
    width: 100%;
  }
  .directory-sidebar {
    grid-template-columns: minmax(0, 1fr);
  }
  .results-header {
    flex-wrap: wrap;
  }
  .results-header > div {
    flex-wrap: wrap;
    gap: 8px;
  }
}
</style>
