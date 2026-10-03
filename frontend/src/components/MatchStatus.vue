<script setup>
import Icon from "./Icon.vue";
defineProps({ verified: Boolean });
</script>
<template>
  <span
    class="data-status"
    :class="verified ? 'verified' : 'historical'"
    :title="
      verified
        ? '公开比赛明细已通过入库校验'
        : '历史导入记录，尚未核验完整源数据'
    "
    ><Icon v-if="verified" name="check" />{{
      verified ? "已核验" : "历史导入"
    }}</span
  >
</template>
