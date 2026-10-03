<script setup>
import { computed, ref } from "vue";
import { useRouter } from "vue-router";
import { request } from "./services/api.js";
import { useResource } from "./composables/useResource.js";
import { number, date, timestamp } from "./utils/format.js";
import Icon from "./components/Icon.vue";

const router = useRouter();
const searchName = ref("");
const {
  data: sync,
  loading,
  error,
  reload,
} = useResource((signal) => request("/api/sync/status", { signal }));
const nav = [
  ["/", "首页"],
  ["/match", "比赛"],
  ["/player", "选手"],
  ["/team", "战队"],
  ["/hero", "英雄"],
  ["/analytics", "数据分析"],
];
const labels = {
  success: "最近采集已完成",
  completed: "最近采集已完成",
  running: "最近采集未完成",
  partial: "部分完成",
  failed: "采集失败",
  cancelled: "已停止",
  budget_exhausted: "最近批次待续采",
  interrupted: "采集已中断，等待恢复",
  waiting_retry: "等待重试",
  stale: "源站暂无近期赛程",
};
const syncLabel = computed(() =>
  sync.value?.last_run
    ? labels[sync.value.last_run.status] || sync.value.last_run.status
    : "等待首次采集",
);
const updatedAt = computed(
  () => sync.value?.last_run?.finished_at || sync.value?.last_run?.started_at,
);
function search() {
  if (searchName.value.trim())
    router.push({
      path: "/player",
      query: { player_name: searchName.value.trim() },
    });
}
</script>
<template>
  <a class="skip-link" href="#main">跳转到内容</a>
  <header class="site-header">
    <div class="header-inner">
      <RouterLink to="/" class="brand" aria-label="LOL 赛事数据首页"
        ><span class="brand-mark">LOL</span
        ><span>赛事数据<small>比赛 · 选手 · 战队</small></span></RouterLink
      >
      <nav class="main-nav" aria-label="主导航">
        <RouterLink
          v-for="[path, label] in nav"
          :key="path"
          :to="path"
          :exact-active-class="path === '/' ? 'active' : ''"
          :active-class="path === '/' ? '' : 'active'"
          >{{ label }}</RouterLink
        >
      </nav>
      <form class="header-search" @submit.prevent="search">
        <label class="sr-only" for="global-search">搜索选手</label
        ><input
          id="global-search"
          v-model="searchName"
          type="search"
          placeholder="搜索选手，如 Faker"
        /><button aria-label="搜索选手"><Icon name="search" /></button>
      </form>
    </div>
  </header>
  <div class="sync-bar">
    <div class="sync-inner">
      <span
        class="sync-indicator"
        :class="{
          failed: error || sync?.last_run?.status === 'failed',
          running: ['running', 'partial'].includes(sync?.last_run?.status),
        }"
      ></span
      ><span>{{
        loading ? "读取采集状态…" : error ? "采集状态暂不可用" : syncLabel
      }}</span
      ><span v-if="updatedAt" class="sync-time"
        >最近更新 {{ timestamp(updatedAt) }}（香港时间）</span
      ><span v-if="sync?.data_range?.min_date" class="sync-range"
        >已确认赛程：{{ date(sync.data_range.min_date) }} 至
        {{ date(sync.data_range.max_date) }}</span
      ><button
        class="text-button sync-refresh"
        :disabled="loading"
        @click="reload"
      >
        <Icon name="refresh" />刷新状态
      </button>
    </div>
  </div>
  <main id="main" class="main-shell"><RouterView /></main>
  <footer class="site-footer">
    <div>
      <strong>LOL 赛事数据</strong
      ><span v-if="sync"
        >历史导入 {{ number(sync.legacy_matches) }} 场 · 已核验
        {{ number(sync.verified_matches) }} 场<span
          v-if="sync.schedule?.enabled"
        >
          · 每日 {{ sync.schedule.time }}（香港时间）采集</span
        ></span
      ><a
        href="https://github.com/Zhong-Ze-Wei"
        target="_blank"
        rel="noopener noreferrer"
        >GitHub</a
      >
    </div>
    <p>
      数据范围以已收录样本为准。部分历史记录仍只有源更新时间，时间分析仅使用确认赛程。
    </p>
  </footer>
</template>
