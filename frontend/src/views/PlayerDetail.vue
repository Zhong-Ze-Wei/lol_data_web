<script setup>
import { computed, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { request } from "../services/api.js";
import { useResource } from "../composables/useResource.js";
import {
  number,
  percent,
  position,
  date,
  resultLabel,
  detailLink,
} from "../utils/format.js";
import { radarOption, trendOption } from "../utils/charts.js";
import ResourceState from "../components/ResourceState.vue";
import Chart from "../components/Chart.vue";
import Pagination from "../components/Pagination.vue";

const route = useRoute();
const router = useRouter();
const name = computed(() => route.params.name);
const resource = useResource(
  (signal) =>
    request(`/player/api/${encodeURIComponent(name.value)}`, {
      params: { page: route.query.page },
      signal,
    }),
  [name, () => route.query.page],
);
const analytics = useResource(
  (signal) =>
    request(`/player/api/${encodeURIComponent(name.value)}/analytics`, {
      signal,
    }),
  [name],
);
const trendMetric = ref("kda");
const trendLabel = computed(
  () =>
    ({
      kda: "KDA",
      atk_p: "伤害占比（%）",
      part: "参团率（%）",
      money_M: "分均经济",
      win_rate: "胜率（%）",
    })[trendMetric.value],
);
const radarAxes = computed(() =>
  (analytics.data.value?.axes || []).filter(
    (axis) =>
      analytics.data.value.percentiles[axis.key] !== null &&
      analytics.data.value.percentiles[axis.key] !== undefined,
  ),
);
const chart = computed(
  () =>
    analytics.data.value &&
    radarOption(radarAxes.value, [
      { ...analytics.data.value, name: name.value },
    ]),
);
const records = computed(() => resource.data.value?.players || []);
function page(value) {
  router.push({ path: route.path, query: { ...route.query, page: value } });
}
</script>
<template>
  <RouterLink class="back-link" to="/player">← 选手档案</RouterLink>
  <header class="page-heading">
    <div>
      <span class="eyebrow">选手档案</span>
      <h1>{{ name }}</h1>
      <p>出场记录、英雄使用与同位置表现。</p>
    </div>
    <RouterLink class="text-link" to="/analytics">进入比较分析 →</RouterLink>
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
                v-if="resource.data.value.pic"
                class="profile-photo"
                :src="resource.data.value.pic"
                :alt="`${name} 的来源头像`"
              />
              <span v-else class="profile-monogram" aria-hidden="true">{{
                String(name).slice(0, 1)
              }}</span>
              <strong>{{ name }}</strong>
              <span class="tag">{{
                resource.data.value.main_position
                  ? position(resource.data.value.main_position)
                  : "未知位置"
              }}</span>
            </div>
            <dl class="detail-facts">
              <div>
                <dt>已收录出场</dt>
                <dd>{{ number(resource.data.value.stats.totalMatches) }} 局</dd>
              </div>
              <div class="latest-confirmed-date">
                <dt>最新确认日期</dt>
                <dd>
                  {{
                    resource.data.value.latest_match_date
                      ? date(resource.data.value.latest_match_date)
                      : "—"
                  }}
                </dd>
              </div>
              <div>
                <dt>样本胜率</dt>
                <dd>{{ percent(resource.data.value.stats.winRate) }}</dd>
              </div>
              <div>
                <dt>已知胜负</dt>
                <dd>{{ number(resource.data.value.stats.knownResults) }} 局</dd>
              </div>
              <div>
                <dt>使用英雄</dt>
                <dd>{{ number(resource.data.value.stats.heroPool) }} 个</dd>
              </div>
            </dl>
            <p class="detail-note">
              统计基于已收录记录，不代表完整生涯。胜率仅使用已知胜负；最新确认日期取全部记录中的已确认赛程。
            </p>
          </section>
          <section class="panel section-space">
            <header class="panel-header"><h2>出场表现</h2></header>
            <dl class="detail-facts">
              <div>
                <dt>场均击杀 / 死亡 / 助攻</dt>
                <dd>{{ resource.data.value.stats.avgKDA || "—" }}</dd>
              </div>
              <div>
                <dt>分均伤害</dt>
                <dd>{{ number(resource.data.value.stats.avgAtkM, 1) }}</dd>
              </div>
              <div>
                <dt>伤害有效样本</dt>
                <dd>
                  {{ number(resource.data.value.stats.avgAtkMSamples) }} 局
                </dd>
              </div>
            </dl>
            <p class="detail-note">
              缺失指标不计为零；分均伤害仅使用有可信时长与伤害的出场。
            </p>
          </section>
        </aside>
        <div class="detail-content">
          <div class="analysis-grid">
            <section class="panel">
              <header class="panel-header">
                <div>
                  <h2>同位置表现轮廓</h2>
                </div>
              </header>
              <ResourceState
                :loading="analytics.loading.value"
                :error="analytics.error.value"
                :empty="!analytics.data.value?.matches_count"
                @retry="analytics.reload"
                ><Chart
                  v-if="chart && radarAxes.length >= 3"
                  :option="chart"
                  :label="`${name} 同位置百分位雷达图`"
                />
                <div v-if="radarAxes.length < 3" class="state-box">
                  有效样本不足或共同指标缺失，暂不绘制雷达。
                </div>
                <p class="chart-note">
                  同位置
                  {{ analytics.data.value?.cohort_size }}
                  位选手的指标百分位。承伤表示赛场职责；各轴独立，不能相加作为综合实力。
                </p></ResourceState
              >
            </section>
            <section class="panel">
              <header class="panel-header">
                <div>
                  <h2>按月观察</h2>
                </div>
                <label
                  ><span class="sr-only">趋势指标</span
                  ><select v-model="trendMetric">
                    <option value="kda">KDA</option>
                    <option value="part">参团率</option>
                    <option value="atk_p">伤害占比</option>
                    <option value="money_M">分均经济</option>
                    <option value="win_rate">胜率</option>
                  </select></label
                >
              </header>
              <ResourceState
                :loading="analytics.loading.value"
                :error="analytics.error.value"
                :empty="!analytics.data.value?.monthly.length"
                @retry="analytics.reload"
                ><Chart
                  :option="
                    trendOption(
                      analytics.data.value.monthly,
                      trendMetric,
                      trendLabel,
                    )
                  "
                  :label="`${name} 月度${trendLabel}`"
                />
                <p class="chart-note">
                  {{
                    analytics.data.value?.date_policy ||
                    "月度趋势仅使用已确认赛程，按开赛日期分月。"
                  }}悬停查看原始指标和比赛样本数。
                </p></ResourceState
              >
            </section>
          </div>
          <section class="panel section-space">
            <header class="panel-header">
              <div>
                <h2>英雄使用</h2>
              </div>
            </header>
            <ResourceState
              :loading="analytics.loading.value"
              :error="analytics.error.value"
              :empty="!analytics.data.value?.heroes.length"
              @retry="analytics.reload"
              ><div class="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>英雄</th>
                      <th class="numeric">出场样本</th>
                      <th class="numeric">胜率</th>
                      <th class="numeric">KDA</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr
                      v-for="hero in analytics.data.value.heroes"
                      :key="hero.hero"
                    >
                      <td>
                        <RouterLink :to="detailLink('hero', hero.hero)">{{
                          hero.hero
                        }}</RouterLink>
                      </td>
                      <td class="numeric">{{ number(hero.matches_count) }}</td>
                      <td class="numeric">{{ percent(hero.win_rate) }}</td>
                      <td class="numeric">{{ number(hero.kda, 2) }}</td>
                    </tr>
                  </tbody>
                </table>
              </div></ResourceState
            >
          </section>
          <section class="panel section-space">
            <header class="panel-header">
              <div>
                <h2>已收录出场记录</h2>
              </div>
              <span class="tag"
                >{{ number(resource.data.value.stats.totalMatches) }} 局</span
              >
            </header>
            <div class="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>比赛日期</th>
                    <th>英雄</th>
                    <th>位置</th>
                    <th>结果</th>
                    <th class="numeric">击杀 / 死亡 / 助攻</th>
                    <th class="numeric">分均伤害</th>
                    <th class="numeric">总经济</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="record in records" :key="record.match_id">
                    <td class="muted">{{ date(record.date) }}</td>
                    <td>
                      <RouterLink
                        v-if="record.hero"
                        :to="detailLink('hero', record.hero)"
                        >{{ record.hero }}</RouterLink
                      >
                      <span v-else>—</span>
                    </td>
                    <td>{{ position(record.position) }}</td>
                    <td
                      :class="
                        resultLabel(record.result) === '胜'
                          ? 'positive'
                          : 'muted'
                      "
                    >
                      {{ resultLabel(record.result) }}
                    </td>
                    <td class="numeric">
                      {{ number(record.kills) }} / {{ number(record.deaths) }} /
                      {{ number(record.assists) }}
                    </td>
                    <td class="numeric">{{ number(record.atk_m) }}</td>
                    <td class="numeric">{{ number(record.money) }}</td>
                    <td>
                      <RouterLink
                        class="detail-button"
                        :to="detailLink('match', record.match_id)"
                        :aria-label="`查看比赛 ${record.match_id}`"
                        >查看详情</RouterLink
                      >
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <Pagination
              :pagination="resource.data.value.pagination"
              @page="page"
            />
          </section>
        </div>
      </div> </template
  ></ResourceState>
</template>
