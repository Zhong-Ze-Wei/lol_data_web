<script setup>
import { computed } from "vue";
import { request } from "./services/api.js";
import { useResource } from "./composables/useResource.js";
import { number, date, timestamp } from "./utils/format.js";

const {
  data: sync,
  loading,
  error,
  reload,
} = useResource((signal) => request("/api/sync/status", { signal }));
const nav = [
  ["/", "总览", "01"],
  ["/player", "选手", "02"],
  ["/match", "比赛", "03"],
  ["/team", "战队", "04"],
  ["/hero", "英雄", "05"],
  ["/analytics", "分析", "06"],
];
const labels = {
  success: "采集完成",
  completed: "采集完成",
  running: "采集中",
  partial: "部分完成",
  failed: "采集失败",
  cancelled: "已停止",
};
const syncLabel = computed(() =>
  sync.value?.last_run
    ? labels[sync.value.last_run.status] || sync.value.last_run.status
    : "等待首次采集",
);
const updatedAt = computed(
  () => sync.value?.last_run?.finished_at || sync.value?.last_run?.started_at,
);
</script>
<template>
  <a class="skip-link" href="#main">跳转到内容</a>
  <header class="site-header">
    <div class="header-inner">
      <RouterLink to="/" class="brand" aria-label="LOL DATA 首页"
        ><span class="brand-mark" aria-hidden="true">L<span>·</span>D</span
        ><span>LOL DATA<small>赛事数据研究台</small></span></RouterLink
      >
      <nav class="main-nav" aria-label="主导航">
        <RouterLink
          v-for="[path, label, index] in nav"
          :key="path"
          :to="path"
          :exact-active-class="path === '/' ? 'active' : ''"
          :active-class="path === '/' ? '' : 'active'"
          ><span>{{ index }}</span
          >{{ label }}</RouterLink
        >
      </nav>
      <a
        class="github-link"
        href="https://github.com/Zhong-Ze-Wei"
        target="_blank"
        rel="noopener noreferrer"
        aria-label="在新窗口打开作者 GitHub"
        >GitHub ↗</a
      >
    </div>
    <div class="sync-bar">
      <div class="sync-inner">
        <span
          class="sync-indicator"
          :class="{
            failed: error || sync?.last_run?.status === 'failed',
            running: ['running', 'partial'].includes(sync?.last_run?.status),
          }"
        ></span>
        <span>{{
          loading ? "读取采集状态…" : error ? "采集状态暂不可用" : syncLabel
        }}</span>
        <span v-if="updatedAt" class="sync-time"
          >最近任务（香港）{{ timestamp(updatedAt) }}</span
        >
        <span v-if="sync?.data_range?.min_date" class="sync-range"
          >收录日期 {{ date(sync.data_range.min_date) }} —
          {{ date(sync.data_range.max_date) }}</span
        >
        <button
          class="text-button"
          :disabled="loading"
          @click="reload"
          aria-label="刷新采集状态"
        >
          刷新 ↻
        </button>
      </div>
    </div>
  </header>
  <main id="main" class="main-shell"><RouterView /></main>
  <footer class="site-footer">
    <div><strong>LOL DATA</strong> <span>采集 · 整理 · 探索</span></div>
    <p>
      基于已收录赛事样本。历史日期来自源数据更新时间，尚未验证为比赛开赛日期。
    </p>
    <span v-if="sync"
      >已校验 {{ number(sync.verified_matches) }} 场 · 历史导入
      {{ number(sync.legacy_matches) }} 场<span v-if="sync.schedule?.enabled">
        · 每日 {{ sync.schedule.time }}（香港时间）采集</span
      ></span
    >
  </footer>
</template>
