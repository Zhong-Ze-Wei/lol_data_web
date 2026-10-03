<script setup>
import { computed, onScopeDispose, ref } from "vue";
import { request } from "../services/api.js";
import { useResource } from "../composables/useResource.js";
import { number, percent, duration, detailLink } from "../utils/format.js";
import { renderAnswer } from "../utils/markdown.js";
import ResourceState from "../components/ResourceState.vue";
import DataTable from "../components/DataTable.vue";

const stats = useResource((signal) => request("/api/stats", { signal }));
const tabs = [
  { key: "top-players", label: "参赛选手", collection: "players" },
  { key: "top-teams", label: "战队胜率", collection: "teams" },
  { key: "fastest-matches", label: "最快比赛", collection: "matches" },
  { key: "longest-matches", label: "最长比赛", collection: "matches" },
  { key: "top-kills", label: "单场击杀", collection: "players" },
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
const examples = [
  "已收录数据中，参赛场次最多的五位选手是谁？",
  "比较 T1 和 GEN 的比赛场数与胜率。",
];
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
  <section class="overview-hero">
    <div class="hero-copy">
      <p class="eyebrow">
        <span class="tiny-rule"></span> LEAGUE OF LEGENDS / DATA LAB
      </p>
      <h1>读懂赛场，<br />从每一条<span>数据</span>开始。</h1>
      <p class="hero-description">
        把比赛记录、选手表现与战队战绩放在同一张研究台上。<br
          class="desktop-only"
        />沿着真实样本，找到你的下一个问题。
      </p>
      <RouterLink class="button" to="/analytics"
        >开始比较分析 <span>↗</span></RouterLink
      ><RouterLink class="text-link hero-secondary" to="/match"
        >浏览比赛 →</RouterLink
      >
    </div>
    <div class="stats-board">
      <div class="board-label">
        <span>ARCHIVE / 收录概况</span
        ><span class="crosshair" aria-hidden="true">＋</span>
      </div>
      <ResourceState
        :loading="stats.loading.value"
        :error="stats.error.value"
        @retry="stats.reload"
        ><div
          v-for="[key, label, unit] in [
            ['matches', '比赛记录', 'MATCHES'],
            ['players', '选手档案', 'PLAYERS'],
            ['teams', '战队档案', 'TEAMS'],
          ]"
          :key="key"
          class="hero-stat"
        >
          <span
            >{{ label }}<small>{{ unit }}</small></span
          ><strong>{{ number(stats.data.value?.stats?.[key]) }}</strong>
        </div></ResourceState
      >
      <div class="board-foot">以数据库实际收录数据为准 <span>↗</span></div>
    </div>
  </section>

  <div class="home-grid">
    <section class="panel ai-panel">
      <header class="panel-header">
        <div>
          <p class="eyebrow">ASK THE ARCHIVE</p>
          <h2>向数据提问</h2>
        </div>
        <span class="tag">AI 助手</span>
      </header>
      <p class="muted">
        用一句话探索数据库。回答会附上实际查询结果，方便核对。
      </p>
      <form @submit.prevent="ask">
        <label class="sr-only" for="ai-prompt">输入赛事数据问题</label
        ><textarea
          id="ai-prompt"
          v-model="prompt"
          :disabled="aiLoading"
          maxlength="1000"
          rows="3"
          placeholder="例如：比较不同位置选手的分均伤害与参团率…"
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
              {{ aiLoading ? "查询中…" : "查询数据 ↗" }}
            </button>
          </div>
        </div>
      </form>
      <div v-if="!result && !aiLoading && !aiError" class="example-queries">
        <span>试着问</span
        ><button
          v-for="example in examples"
          :key="example"
          @click="prompt = example"
        >
          {{ example }} ↗
        </button>
      </div>
      <div v-if="aiLoading" class="state-box" role="status">
        <span class="spinner"></span> 正在查询并整理回答…
      </div>
      <div v-if="aiError" class="ai-error" role="alert">
        {{ aiError }}
        <p class="muted small-text">
          可以继续使用选手、比赛、战队和比较分析页面。
        </p>
      </div>
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
        <div>
          <p class="eyebrow">IN THE NUMBERS</p>
          <h2>档案速览</h2>
        </div>
        <span class="section-number">02</span>
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
              ><span class="rank-number">{{
                String(index + 1).padStart(2, "0")
              }}</span>
              <div class="rank-name">
                <strong>{{
                  active.collection === "matches"
                    ? `${row.blue_team_name} / ${row.red_team_name}`
                    : row.name || row.team_name
                }}</strong
                ><small v-if="active.key === 'top-kills'"
                  >{{ row.team_name }} · {{ row.hero }}</small
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
              }}</span></RouterLink
            >
          </li>
        </ol></ResourceState
      >
      <p class="small-text muted ranking-foot">
        排名仅覆盖已收录样本；小样本胜率请结合场次阅读。
      </p>
    </section>
  </div>
  <section class="pathways">
    <RouterLink
      v-for="[path, index, title, text] in [
        ['/player', '01', '选手档案', '从出场记录，到英雄池与表现趋势。'],
        ['/match', '02', '比赛复盘', '查看双方阵容、经济与赛场明细。'],
        ['/analytics', '03', '同位置比较', '用原始指标和百分位理解不同风格。'],
      ]"
      :key="path"
      :to="path"
      ><span class="eyebrow">EXPLORE / {{ index }}</span>
      <h3>{{ title }} <span>↗</span></h3>
      <p>{{ text }}</p></RouterLink
    >
  </section>
</template>
