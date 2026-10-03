<script setup>
import { computed, onScopeDispose, ref, shallowRef, watch } from "vue";
import { useRouter } from "vue-router";
import { request } from "./services/api.js";
import { useResource } from "./composables/useResource.js";
import { number, date, timestamp } from "./utils/format.js";
import { syncFeedback } from "./utils/history.js";
import Icon from "./components/Icon.vue";

const router = useRouter();
const searchName = ref("");
const {
  data: currentSync,
  loading,
  error,
  reload,
} = useResource(async (signal) => {
  const requestedAt = performance.now();
  const result = await request("/api/sync/status", { signal });
  return { result, requestedAt, receivedAt: performance.now() };
});
const latestSync = shallowRef(null);
const stateRequestedAt = ref(performance.now());
const clock = ref(stateRequestedAt.value);
const updatedAt = ref(null);
const statusUnavailable = ref(false);
watch(error, (value) => {
  if (value) statusUnavailable.value = true;
});
watch(currentSync, (value) => {
  if (value) {
    latestSync.value = value.result;
    // 整次请求耗时计入保守心跳年龄；新请求挂起时仍沿用上一成功响应的起点。
    stateRequestedAt.value = value.requestedAt;
    clock.value = value.receivedAt;
    updatedAt.value = new Date().toISOString();
    statusUnavailable.value = false;
  }
});
const sync = computed(() => currentSync.value?.result || latestSync.value);
const feedback = computed(() =>
  syncFeedback(sync.value, (clock.value - stateRequestedAt.value) / 1000),
);
const clockTimer = setInterval(() => {
  clock.value = performance.now();
}, 15000);
const refreshTimer = setInterval(() => {
  if (!loading.value) reload();
}, 30000);
onScopeDispose(() => {
  clearInterval(clockTimer);
  clearInterval(refreshTimer);
});
const nav = [
  ["/", "首页"],
  ["/match", "比赛"],
  ["/player", "选手"],
  ["/team", "战队"],
  ["/hero", "英雄"],
  ["/analytics", "数据分析"],
];
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
          failed: statusUnavailable || feedback.failed,
          running: !statusUnavailable && !feedback.failed && feedback.running,
        }"
      ></span
      ><span>{{
        statusUnavailable
          ? "采集状态暂不可用"
          : loading && !sync
            ? "读取采集状态…"
            : feedback.label
      }}</span
      ><span v-if="updatedAt" class="sync-time"
        >采集状态更新 {{ timestamp(updatedAt) }}（香港时间）</span
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
