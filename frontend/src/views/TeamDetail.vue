<script setup>
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";
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
import Pagination from "../components/Pagination.vue";
const route = useRoute();
const router = useRouter();
const name = computed(() => route.params.team_name);
const resource = useResource(
  (signal) =>
    request(`/team/api/${encodeURIComponent(name.value)}`, {
      params: { page: route.query.page },
      signal,
    }),
  [name, () => route.query.page],
);
function page(value) {
  router.push({ path: route.path, query: { ...route.query, page: value } });
}
</script>
<template>
  <RouterLink class="back-link" to="/team">← 战队档案</RouterLink>
  <header class="page-heading">
    <p class="eyebrow">TEAM PROFILE / ARCHIVE</p>
    <h1>{{ name }}</h1>
    <p>战绩与阵容以已收录比赛为依据。</p>
  </header>
  <ResourceState
    :loading="resource.loading.value"
    :error="resource.error.value"
    @retry="resource.reload"
    ><template v-if="resource.data.value"
      ><div class="metric-grid">
        <div class="metric">
          <span>出场样本</span
          ><strong>{{ number(resource.data.value.matches_count) }}</strong>
        </div>
        <div class="metric">
          <span>样本胜率</span
          ><strong>{{ percent(resource.data.value.win_rate) }}</strong>
        </div>
        <div class="metric metric-action">
          <span>比较不同战队</span
          ><RouterLink
            class="text-link"
            :to="{
              path: '/analytics',
              query: { tab: 'teams', team_names: name },
            }"
            >加入战队比较 ↗</RouterLink
          >
        </div>
      </div>
      <section class="panel">
        <header class="panel-header">
          <div>
            <p class="eyebrow">LATEST RECORDED LINEUP</p>
            <h2>最近收录阵容</h2>
          </div>
          <span class="tag">历史记录</span>
        </header>
        <div class="lineup">
          <RouterLink
            v-for="player in resource.data.value.players"
            :key="player.player_name"
            :to="detailLink('player', player.player_name)"
            ><span class="eyebrow">{{ position(player.position) }}</span
            ><strong>{{ player.player_name }}</strong
            ><span class="row-arrow">↗</span></RouterLink
          >
          <p v-if="!resource.data.value.players.length" class="muted">
            暂无阵容记录。
          </p>
        </div>
      </section>
      <section class="panel section-space">
        <header class="panel-header">
          <div>
            <p class="eyebrow">RECENT MATCHES</p>
            <h2>最近比赛记录</h2>
          </div>
          <RouterLink
            class="text-link"
            :to="{ path: '/match', query: { team_name1: name } }"
            >筛选全部比赛 →</RouterLink
          >
        </header>
        <ResourceState :empty="!resource.data.value.matches?.length"
          ><div class="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>记录日期</th>
                  <th>双方战队</th>
                  <th>获胜队伍</th>
                  <th class="numeric">比赛时长</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="match in resource.data.value.matches"
                  :key="match.match_id"
                >
                  <td class="muted">{{ date(match.date) }}</td>
                  <td>
                    {{ match.blue_team_name }} <span class="versus">/</span>
                    {{ match.red_team_name }}
                  </td>
                  <td
                    :class="match.win_team_name === name ? 'positive' : 'muted'"
                  >
                    {{ match.win_team_name }}
                  </td>
                  <td class="numeric">{{ duration(match.game_time) }}</td>
                  <td>
                    <RouterLink
                      class="row-arrow"
                      :to="detailLink('match', match.match_id)"
                      :aria-label="`查看比赛 ${match.match_id}`"
                      >↗</RouterLink
                    >
                  </td>
                </tr>
              </tbody>
            </table>
          </div></ResourceState
        >
        <Pagination
          :pagination="resource.data.value.pagination"
          @page="page"
        /></section></template
  ></ResourceState>
</template>
