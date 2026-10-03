<script setup>
defineProps({
  loading: Boolean,
  error: String,
  empty: Boolean,
  emptyText: { type: String, default: "暂时没有符合条件的数据。" },
});
defineEmits(["retry"]);
</script>
<template>
  <div v-if="loading" class="state-box" role="status">
    <span class="spinner" aria-hidden="true"></span> 正在读取赛事数据…
  </div>
  <div v-else-if="error" class="state-box state-error" role="alert">
    <p>{{ error }}</p>
    <button class="button secondary small" @click="$emit('retry')">
      重新加载
    </button>
  </div>
  <div v-else-if="empty" class="state-box">
    <span class="empty-mark" aria-hidden="true">∅</span>{{ emptyText }}
  </div>
  <slot v-else />
</template>
