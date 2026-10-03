<script setup>
import { computed, onScopeDispose, ref } from "vue";
import { request } from "../services/api.js";
import { useResource } from "../composables/useResource.js";
import {
  number,
  percent,
  duration,
  date,
  detailLink,
} from "../utils/format.js";
import { renderAnswer } from "../utils/markdown.js";
import ResourceState from "../components/ResourceState.vue";
import DataTable from "../components/DataTable.vue";
import Icon from "../components/Icon.vue";
import MatchStatus from "../components/MatchStatus.vue";

const stats = useResource((signal) => request("/api/stats", { signal }));
const recent = useResource((signal) =>
  request("/api/recent-matches", { signal }),
);
const recentMatches = computed(() =>
  (recent.data.value?.matches || []).slice(0, 6),
);
const statItems = [
  ["matches", "比赛记录", "match", "/match"],
  ["players", "选手档案", "player", "/player"],
  ["teams", "战队档案", "team", "/team"],
  ["verified_matches", "已核验比赛", "check", "/match"],
];
const tabs = [
  { key: "top-players", label: "选手参赛榜", collection: "players" },
  { key: "top-teams", label: "战队胜率榜", collection: "teams" },
  { key: "fastest-matches", label: "最快比赛", collection: "matches" },
  { key: "longest-matches", label: "最长比赛", collection: "matches" },
  { key: "top-kills", label: "单场击杀榜", collection: "players" },
];
const active = ref(tabs[0]);
const ranking = useResource(
  (signal) => request(`/api/${active.value.key}`, { signal }),
  [active],
);
const rankingRows = computed(
  () => ranking.data.value?.[active.value.collection] || [],
);
const prompt = ref("");
const aiLoading = ref(false);
const aiError = ref("");
const result = ref(null);
const answer = computed(() => renderAnswer(result.value?.answer));
const examples = ["参赛最多的五位选手是谁？", "比较 T1 和 GEN 的胜率。"];
let aiController;
onScopeDispose(() => aiController?.abort());
async function ask() {
  if (!prompt.value.trim() || aiLoading.value) return;
  aiLoading.value = true;
  aiError.value = "";
  result.value = null;
  aiController = new AbortController();
  try {
    const data = await request("/api/ai/query", {
      method: "POST",
      body: { prompt: prompt.value.trim() },
      signal: aiController.signal,
    });
    if (data.result?.error) throw new Error(data.result.error);
    result.value = data.result;
  } catch (error) {
    if (error.name !== "AbortError") aiError.value = error.message;
  } finally {
    aiLoading.value = false;
  }
}
function clear() {
  prompt.value = "";
  result.value = null;
  aiError.value = "";
}
function rowLink(row) {
  if (active.value.collection === "matches")
    return detailLink("match", row.match_id ?? row.id);
  return detailLink(
    active.value.collection === "teams" ? "team" : "player",
    active.value.collection === "teams" ? row.team_name : row.name,
  );
}
</script>
<template>
  <header class="page-heading home-heading">
    <div>
      <h1>赛事数据总览</h1>
      <p>最近比赛、选手表现和战队战绩，在这里一起查看。</p>
    </div>
    <RouterLink class="button secondary small" to="/analytics"
      ><Icon name="chart" />比较分析</RouterLink
    >
  </header>
  <ResourceState
    :loading="stats.loading.value"
    :error="stats.error.value"
    @retry="stats.reload"
    ><section class="overview-stats" aria-label="数据收录概况">
      <RouterLink
        v-for="[key, label, icon, path] in statItems"
        :key="key"
        :to="path"
        class="overview-stat"
        ><span class="stat-icon"><Icon :name="icon" /></span>
        <div>
          <span>{{ label }}</span
          ><strong>{{ number(stats.data.value?.stats?.[key]) }}</strong>
        </div>
        <span class="stat-unit">{{
          key === "players" ? "位" : key === "teams" ? "支" : "场"
        }}</span></RouterLink
      >
    </section></ResourceState
  >
  <div class="portal-grid">
    <section class="panel recent-panel">
      <header class="panel-header">
        <h2><Icon name="match" />最近比赛</h2>
        <RouterLink class="text-link" to="/match"
          >全部比赛 <Icon name="arrow"
        /></RouterLink>
      </header>
      <ResourceState
        :loading="recent.loading.value"
        :error="recent.error.value"
        :empty="!recentMatches.length"
        @retry="recent.reload"
        ><div class="match-feed">
          <article
            v-for="match in recentMatches"
            :key="match.match_id"
            class="match-feed-row"
          >
            <div class="feed-date">
              {{ date(match.date)
              }}<small>{{ match.tournament_name || "历史比赛记录" }}</small>
            </div>
            <div class="feed-matchup">
              <RouterLink
                :to="detailLink('team', match.blue_team_name)"
                :class="{
                  winner: match.win_team_name === match.blue_team_name,
                }"
                >{{ match.blue_team_name
                }}<span
                  v-if="match.win_team_name === match.blue_team_name"
                  class="win-label"
                  >胜</span
                ></RouterLink
              ><span class="versus">VS</span
              ><RouterLink
                :to="detailLink('team', match.red_team_name)"
                :class="{ winner: match.win_team_name === match.red_team_name }"
                >{{ match.red_team_name
                }}<span
                  v-if="match.win_team_name === match.red_team_name"
                  class="win-label"
                  >胜</span
                ></RouterLink
              >
            </div>
            <div class="feed-meta">
              <MatchStatus :verified="match.verified" /><span>{{
                duration(match.game_time)
              }}</span>
            </div>
            <RouterLink
              class="detail-button"
              :to="detailLink('match', match.match_id)"
              >查看详情</RouterLink
            >
          </article>
        </div></ResourceState
      >
    </section>
    <div class="portal-sidebar">
      <section class="panel ai-panel">
        <header class="panel-header">
          <h2><Icon name="ai" />AI 数据助手</h2>
          <span class="tag">自然语言查询</span>
        </header>
        <p class="muted ai-description">
          输入赛事问题，获得基于数据库的回答和查询结果。
        </p>
        <form @submit.prevent="ask">
          <label class="sr-only" for="ai-prompt">输入赛事数据问题</label
          ><textarea
            id="ai-prompt"
            v-model="prompt"
            :disabled="aiLoading"
            maxlength="1000"
            rows="2"
            placeholder="例如：2024 年哪些选手的 KDA 最高？"
            @keydown.ctrl.enter.prevent="ask"
          ></textarea>
          <div class="query-actions">
            <span class="muted small-text">Ctrl + Enter 发送</span>
            <div>
              <button
                class="text-button"
                type="button"
                :disabled="aiLoading"
                @click="clear"
              >
                清空</button
              ><button
                class="button small"
                :disabled="aiLoading || !prompt.trim()"
              >
                {{ aiLoading ? "正在查询…" : "发送问题" }}
              </button>
            </div>
          </div>
        </form>
        <div v-if="!result && !aiLoading && !aiError" class="example-queries">
          <span>你可以这样问：</span
          ><button
            v-for="example in examples"
            :key="example"
            @click="prompt = example"
          >
            {{ example }}
          </button>
        </div>
        <div v-if="aiLoading" class="state-box" role="status">
          <span class="spinner"></span>正在查询并整理回答…
        </div>
        <div v-if="aiError" class="ai-error" role="alert">{{ aiError }}</div>
        <div v-if="result" class="ai-result">
          <div class="markdown" v-html="answer"></div>
          <details v-if="result.data?.length">
            <summary>查看查询结果 · {{ result.data.length }} 条</summary>
            <DataTable :rows="result.data" />
          </details>
          <details v-if="result.sql">
            <summary>查看查询 SQL</summary>
            <pre><code>{{ result.sql }}</code></pre>
          </details>
          <p v-if="!result.data?.length" class="muted small-text">
            本次查询没有返回数据行。
          </p>
        </div>
      </section>
      <section class="panel ranking-panel">
        <header class="panel-header">
          <h2><Icon name="chart" />数据排行</h2>
          <span class="muted small-text">基于已收录样本</span>
        </header>
        <div class="tab-strip">
          <button
            v-for="tab in tabs"
            :key="tab.key"
            :class="{ selected: active.key === tab.key }"
            @click="active = tab"
          >
            {{ tab.label }}
          </button>
        </div>
        <ResourceState
          :loading="ranking.loading.value"
          :error="ranking.error.value"
          :empty="!rankingRows.length"
          @retry="ranking.reload"
          ><ol class="ranking-list">
            <li
              v-for="(row, index) in rankingRows"
              :key="`${row.name || row.team_name || row.match_id || row.id}-${index}`"
            >
              <RouterLink :to="rowLink(row)"
                ><span class="rank-number" :class="{ top: index === 0 }">{{
                  index + 1
                }}</span>
                <div class="rank-name">
                  <strong>{{
                    active.collection === "matches"
                      ? `${row.blue_team_name} vs ${row.red_team_name}`
                      : row.name || row.team_name
                  }}</strong
                  ><small v-if="active.key === 'top-kills'"
                    >{{ row.team_name }} · {{ row.hero || "英雄未记录" }}</small
                  ><small v-else-if="active.key === 'top-teams'"
                    >{{ number(row.matches_count) }} 场样本</small
                  >
                </div>
                <span class="rank-value">{{
                  active.key === "top-teams"
                    ? percent(row.win_rate)
                    : active.collection === "matches"
                      ? duration(row.game_time)
                      : active.key === "top-kills"
                        ? `${number(row.kills)} 杀`
                        : `${number(row.matches_count)} 场`
                }}</span
                ><Icon name="arrow"
              /></RouterLink>
            </li></ol
        ></ResourceState>
      </section>
    </div>
  </div>
  <div class="home-lower-grid">
    <section class="panel quick-panel">
      <header class="panel-header"><h2>常用入口</h2></header>
      <div class="quick-links">
        <RouterLink
          v-for="[path, icon, title, text] in [
            ['/player', 'player', '选手数据', '出场记录、英雄池、月度趋势'],
            ['/team', 'team', '战队数据', '历史战绩、最近阵容'],
            ['/hero', 'hero', '英雄数据', '出场样本、胜率与表现'],
            ['/analytics', 'chart', '比较分析', '同位置雷达与战队比较'],
          ]"
          :key="path"
          :to="path"
          ><span class="quick-icon"><Icon :name="icon" /></span>
          <div>
            <strong>{{ title }}</strong
            ><small>{{ text }}</small>
          </div>
          <Icon name="arrow"
        /></RouterLink>
      </div>
    </section>
  </div>
</template>
