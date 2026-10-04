<script setup>
import { computed } from "vue";
import { useRoute } from "vue-router";
import { request } from "../services/api.js";
import { useResource } from "../composables/useResource.js";
import {
  number,
  percent,
  date,
  duration,
  position,
  detailLink,
} from "../utils/format.js";
import ResourceState from "../components/ResourceState.vue";
import Chart from "../components/Chart.vue";
import MatchStatus from "../components/MatchStatus.vue";

const route = useRoute();
const resource = useResource(
  (signal) =>
    request(`/match/api/${encodeURIComponent(route.params.match_id)}`, {
      signal,
    }),
  [() => route.params.match_id],
);
const match = computed(() => resource.data.value?.match);
const players = computed(() => resource.data.value?.players || []);
const neutralSides = computed(
  () => match.value?.side_basis === "metadata_team_a_b",
);
const sideLabels = computed(() =>
  match.value?.side_basis === "metadata_team_a_b"
    ? { blue: "队伍 A", red: "队伍 B" }
    : { blue: "蓝方", red: "红方" },
);
const hasDamage = computed(() =>
  players.value.some((player) => player.atk != null),
);
const qualityNotice = computed(() => {
  if (!match.value) return "";
  const notes = [];
  if (match.value.side_basis === "metadata_team_a_b") {
    notes.push("红蓝方尚未确认，双方按来源顺序展示");
  }
  if (players.value.some((player) => player.position == null)) {
    notes.push("部分选手位置待确认");
  }
  if (players.value.length < 10) {
    notes.push(
      match.value.verified
        ? "公开战报阵容有缺项，个人统计仅包含已确认选手"
        : "历史记录阵容不完整，个人统计仅包含已收录选手",
    );
  }
  if (match.value.game_time == null || match.value.game_time <= 1) {
    notes.push("缺少可信比赛时长，分均指标未计算");
  }
  const missingMetrics = [
    ["atk", "伤害"],
    ["money", "经济"],
    ["hits", "补刀"],
  ]
    .filter(([key]) => players.value.some((player) => player[key] == null))
    .map(([, label]) => label);
  if (missingMetrics.length) {
    notes.push(`部分${missingMetrics.join("、")}数据缺失，空值未计为零`);
  }
  return notes.length ? `${notes.join("；")}。` : "";
});
const sides = computed(() =>
  resource.data.value
    ? [
        {
          name: sideLabels.value.blue,
          color: "blue",
          team: resource.data.value.blue_team,
          teamName: match.value.blue_team_name,
        },
        {
          name: sideLabels.value.red,
          color: "red",
          team: resource.data.value.red_team,
          teamName: match.value.red_team_name,
        },
      ]
    : [],
);
const damage = computed(() => {
  const players = resource.data.value?.players || [];
  return {
    animation: false,
    tooltip: {
      trigger: "axis",
      renderMode: "richText",
      formatter: (items) => {
        const player = players[items[0].dataIndex];
        return `${player.name} · ${player.hero}\n对英雄总伤害: ${number(player.atk)}\n样本: 本场比赛`;
      },
    },
    grid: { top: 15, bottom: 25, left: 90, right: 30 },
    xAxis: {
      type: "value",
      axisLabel: { color: "#4e5969" },
      splitLine: { lineStyle: { color: "#edf0f4" } },
    },
    yAxis: {
      type: "category",
      inverse: true,
      data: players.map((player) => player.name),
      axisLabel: { color: "#1d2129" },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    series: [
      {
        type: "bar",
        barWidth: 15,
        data: players.map((player) => ({
          value: player.atk,
          itemStyle: {
            color:
              player.team_name === match.value.blue_team_name
                ? "#1677ff"
                : "#ff7d00",
          },
        })),
      },
    ],
  };
});
</script>
<template>
  <RouterLink class="back-link" to="/match">← 比赛记录</RouterLink>
  <header class="page-heading">
    <div>
      <h1>比赛详情</h1>
      <p class="match-context">
        <template v-if="match?.tournament_name"
          >{{ match.tournament_name }} ·
        </template>
        比赛 #{{ route.params.match_id
        }}<span v-if="match"> · 已收录 {{ players.length }}/10 位选手</span>
      </p>
    </div>
    <MatchStatus v-if="match" :verified="match.verified" />
  </header>
  <ResourceState
    :loading="resource.loading.value"
    :error="resource.error.value"
    @retry="resource.reload"
    ><template v-if="match"
      ><p v-if="qualityNotice" class="match-quality-notice" role="status">
        {{ qualityNotice }}
      </p>
      <section class="match-scoreboard">
        <div class="score-team" :class="{ blue: !neutralSides }">
          <span class="eyebrow">{{ sideLabels.blue }}</span
          ><RouterLink :to="detailLink('team', match.blue_team_name)">{{
            match.blue_team_name
          }}</RouterLink
          ><span
            v-if="match.win_team_name === match.blue_team_name"
            class="tag victory"
            >胜利</span
          >
        </div>
        <div class="score-center">
          <span class="versus">VS</span
          ><strong>{{ duration(match.game_time) }}</strong
          ><span>{{ date(match.date) }}</span
          ><small v-if="!match.win_team_name">胜负待确认</small
          ><small v-if="match.mvp">MVP / {{ match.mvp }}</small>
        </div>
        <div class="score-team" :class="{ red: !neutralSides }">
          <span class="eyebrow">{{ sideLabels.red }}</span
          ><RouterLink :to="detailLink('team', match.red_team_name)">{{
            match.red_team_name
          }}</RouterLink
          ><span
            v-if="match.win_team_name === match.red_team_name"
            class="tag victory"
            >胜利</span
          >
        </div>
      </section>
      <div class="analysis-grid">
        <section v-for="side in sides" :key="side.color" class="panel">
          <header class="panel-header">
            <h2 :class="neutralSides ? null : side.color">
              {{ side.teamName }}
            </h2>
            <span class="tag">{{ side.name }}</span>
          </header>
          <div v-if="side.team" class="team-objectives">
            <div
              v-for="[key, label] in [
                ['kill', '击杀'],
                ['money', '总经济'],
                ['tower', '防御塔'],
                ['small_dargon', '小龙'],
                ['big_dargon', '大龙'],
                ['riftHeraldKills', '先锋'],
              ]"
              :key="key"
            >
              <span>{{ label }}</span
              ><strong>{{ number(side.team[key]) }}</strong>
            </div>
          </div>
          <p v-else class="muted">该方战队明细未收录。</p>
        </section>
      </div>
      <section
        v-for="side in sides"
        :key="`${side.color}-players`"
        class="panel section-space"
      >
        <header class="panel-header">
          <h2 :class="neutralSides ? null : side.color">
            {{ side.name }}选手数据
          </h2>
          <span class="eyebrow">{{ side.teamName }}</span>
        </header>
        <div class="table-scroll">
          <table>
            <thead>
              <tr>
                <th>选手</th>
                <th>位置</th>
                <th>英雄</th>
                <th class="numeric">击杀 / 死亡 / 助攻</th>
                <th class="numeric">KDA</th>
                <th class="numeric">参团率</th>
                <th class="numeric">分均伤害</th>
                <th class="numeric">补刀</th>
                <th class="numeric">总经济</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="player in resource.data.value.players.filter(
                  (player) => player.team_name === side.teamName,
                )"
                :key="player.name"
              >
                <td>
                  <RouterLink
                    class="entity-name"
                    :to="detailLink('player', player.name)"
                    >{{ player.name }}</RouterLink
                  >
                </td>
                <td>{{ position(player.position) }}</td>
                <td>
                  <RouterLink
                    v-if="player.hero"
                    :to="detailLink('hero', player.hero)"
                    >{{ player.hero }}</RouterLink
                  >
                  <span v-else>—</span>
                </td>
                <td class="numeric">
                  {{ number(player.kills) }} / {{ number(player.deaths) }} /
                  {{ number(player.assists) }}
                </td>
                <td class="numeric">{{ number(player.kda, 2) }}</td>
                <td class="numeric">{{ percent(player.part) }}</td>
                <td class="numeric">{{ number(player.atk_m) }}</td>
                <td class="numeric">{{ number(player.hits) }}</td>
                <td class="numeric">{{ number(player.money) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
      <section class="panel section-space">
        <header class="panel-header">
          <div>
            <h2>对英雄总伤害</h2>
          </div>
          <span class="tag">本场原始值</span>
        </header>
        <Chart
          v-if="hasDamage"
          :option="damage"
          label="本场已收录选手对英雄总伤害条形图"
          :height="380"
        />
        <p v-else class="muted">本场没有可信伤害记录，未生成伤害图。</p>
        <p class="chart-note">
          伤害受英雄、位置、阵容与比赛时长影响。以上数据仅描述本场比赛。
        </p>
      </section>
    </template></ResourceState
  >
</template>
<style scoped>
.match-context {
  overflow-wrap: anywhere;
}
.match-quality-notice {
  margin: 0 0 16px;
  padding: 11px 14px;
  border: 1px solid #ffe3ba;
  border-radius: 5px;
  background: #fff9ef;
  color: #865a1d;
  font-size: 12px;
  line-height: 1.7;
}
</style>
