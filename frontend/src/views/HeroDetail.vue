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
    <p class="eyebrow">CHAMPION PROFILE / SAMPLE STATISTICS</p>
    <h1>{{ name }}</h1>
    <p>汇总已收录比赛中这个英雄的实际使用表现。</p>
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
        <div class="metric">
          <span>场均 KDA</span
          ><strong>{{ number(resource.data.value.avg_kda, 2) }}</strong>
        </div>
        <div class="metric">
          <span>主要位置</span
          ><strong class="text-metric">{{
            position(resource.data.value.position)
          }}</strong>
        </div>
      </div>
      <section class="panel">
        <header class="panel-header">
          <div>
            <p class="eyebrow">PERFORMANCE METRICS</p>
            <h2>原始表现指标</h2>
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
      </section></template
    ></ResourceState
  >
</template>
