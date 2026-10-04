<script setup>
import { computed } from "vue";
import { useRoute } from "vue-router";
import { request } from "../services/api.js";
import { useResource } from "../composables/useResource.js";
import { number, percent, position } from "../utils/format.js";
import ResourceState from "../components/ResourceState.vue";
const route = useRoute();
const name = computed(() => route.params.hero_name);
const resource = useResource(
  (signal) =>
    request(`/hero/api/${encodeURIComponent(name.value)}`, { signal }),
  [name],
);
</script>
<template>
  <RouterLink class="back-link" to="/hero">← 英雄数据</RouterLink>
  <header class="page-heading">
    <div>
      <span class="eyebrow">英雄出场档案</span>
      <h1>{{ name }}</h1>
      <p>已收录比赛中的英雄使用与表现。</p>
    </div>
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
              <span class="profile-monogram" aria-hidden="true">{{
                String(name).slice(0, 1)
              }}</span>
              <strong>{{ name }}</strong>
              <span class="tag">{{
                resource.data.value.position
                  ? position(resource.data.value.position)
                  : "未知位置"
              }}</span>
            </div>
            <dl class="detail-facts">
              <div>
                <dt>已收录出场</dt>
                <dd>{{ number(resource.data.value.matches_count) }} 次</dd>
              </div>
              <div>
                <dt>样本胜率</dt>
                <dd>{{ percent(resource.data.value.win_rate) }}</dd>
              </div>
              <div>
                <dt>已知胜负</dt>
                <dd>{{ number(resource.data.value.known_results) }} 次</dd>
              </div>
              <div>
                <dt>场均 KDA</dt>
                <dd>{{ number(resource.data.value.avg_kda, 2) }}</dd>
              </div>
            </dl>
            <p class="detail-note">
              统计单位为选手使用该英雄的出场。未知胜负不进入胜率分母，缺失指标不计为零。
            </p>
          </section>
        </aside>
        <div class="detail-content">
          <section class="panel">
            <header class="panel-header">
              <div>
                <h2>出场表现汇总</h2>
              </div>
            </header>
            <div class="hero-metrics">
              <div
                v-for="[key, label] in [
                  ['avg_kills', '场均击杀'],
                  ['avg_deaths', '场均死亡'],
                  ['avg_assists', '场均助攻'],
                  ['avg_damage', '场均总伤害'],
                  ['avg_gold', '场均经济'],
                  ['avg_cs', '场均补刀'],
                ]"
                :key="key"
              >
                <span>{{ label }}</span
                ><strong>{{ number(resource.data.value[key], 1) }}</strong>
              </div>
            </div>
            <p class="chart-note">
              样本可能跨越不同赛事、版本和时间段；出场表现受位置与阵容影响。
            </p>
          </section>
        </div>
      </div></template
    ></ResourceState
  >
</template>
