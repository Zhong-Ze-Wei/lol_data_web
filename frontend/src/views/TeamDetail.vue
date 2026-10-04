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
    <div>
      <span class="eyebrow">战队档案</span>
      <h1>{{ name }}</h1>
      <p>已收录战绩、阵容与比赛记录。</p>
    </div>
    <RouterLink
      class="text-link"
      :to="{ path: '/analytics', query: { tab: 'teams', team_names: name } }"
      >比较战队 →</RouterLink
    >
  </header>
  <ResourceState
    :loading="resource.loading.value"
    :error="resource.error.value"
    @retry="resource.reload"
    ><template v-if="resource.data.value"
      ><div class="detail-layout">
        <aside class="detail-sidebar">
          <section class="panel detail-summary">
            <div class="detail-identity">
              <img
                v-if="resource.data.value.team_flag"
                class="profile-photo team-logo"
                :src="resource.data.value.team_flag"
                :alt="`${name} 的来源队徽`"
              />
              <span v-else class="profile-monogram" aria-hidden="true">{{
                String(name).slice(0, 1)
              }}</span>
              <strong>{{ name }}</strong>
              <span class="tag">已收录战队记录</span>
            </div>
            <dl class="detail-facts">
              <div>
                <dt>已收录出场</dt>
                <dd>{{ number(resource.data.value.matches_count) }} 局</dd>
              </div>
              <div>
                <dt>样本胜率</dt>
                <dd>{{ percent(resource.data.value.win_rate) }}</dd>
              </div>
              <div>
                <dt>已知胜负</dt>
                <dd>{{ number(resource.data.value.known_results) }} 局</dd>
              </div>
              <div>
                <dt>已知胜局</dt>
                <dd>{{ number(resource.data.value.wins) }} 局</dd>
              </div>
            </dl>
            <p class="detail-note">
              胜率仅计已知胜负。名称按来源记录展示，不自动合并历史更名；收录范围仍在补充。
            </p>
          </section>
        </aside>
        <div class="detail-content">
          <section class="panel">
            <header class="panel-header">
              <div>
                <h2>最近收录阵容</h2>
              </div>
              <span class="tag">历史记录</span>
            </header>
            <p class="detail-note lineup-note">
              阵容来自已收录的最近一场记录，不代表当前签约阵容。
            </p>
            <div class="lineup">
              <RouterLink
                v-for="player in resource.data.value.players"
                :key="player.player_name"
                :to="detailLink('player', player.player_name)"
                ><span class="eyebrow">{{ position(player.position) }}</span
                ><strong>{{ player.player_name }}</strong
                ><span class="detail-button">查看选手</span></RouterLink
              >
              <p v-if="!resource.data.value.players.length" class="muted">
                暂无阵容记录。
              </p>
            </div>
          </section>
          <section class="panel section-space">
            <header class="panel-header">
              <div>
                <h2>最近比赛记录</h2>
              </div>
              <RouterLink
                class="text-link"
                :to="{ path: '/match', query: { team_name1: name } }"
                >查看全部比赛</RouterLink
              >
            </header>
            <ResourceState :empty="!resource.data.value.matches?.length"
              ><div class="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>比赛日期</th>
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
                        :class="
                          match.win_team_name === name ? 'positive' : 'muted'
                        "
                      >
                        {{ match.win_team_name || "胜负待确认" }}
                      </td>
                      <td class="numeric">{{ duration(match.game_time) }}</td>
                      <td>
                        <RouterLink
                          class="detail-button"
                          :to="detailLink('match', match.match_id)"
                          :aria-label="`查看比赛 ${match.match_id}`"
                          >查看详情</RouterLink
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
            />
          </section>
        </div></div></template
  ></ResourceState>
</template>
