<script setup>
defineProps({ pagination: Object });
defineEmits(["page"]);
</script>
<template>
  <nav v-if="pagination?.pages > 1" class="pagination" aria-label="结果分页">
    <span
      >第 <strong>{{ pagination.page }}</strong> /
      {{ pagination.pages }} 页<span v-if="pagination.total !== undefined">
        · {{ pagination.total }} 条</span
      ></span
    >
    <div>
      <button
        class="button secondary small"
        :disabled="!pagination.has_prev"
        @click="$emit('page', pagination.prev_num)"
      >
        ← 上一页</button
      ><button
        class="button secondary small"
        :disabled="!pagination.has_next"
        @click="$emit('page', pagination.next_num)"
      >
        下一页 →
      </button>
    </div>
  </nav>
</template>
