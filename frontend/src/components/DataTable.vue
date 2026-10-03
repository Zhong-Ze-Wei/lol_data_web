<script setup>
import { computed } from "vue";
import { formatCell } from "../utils/ai.js";
const props = defineProps({
  rows: { type: Array, required: true },
  columns: { type: Array, default: () => [] },
});
const headings = computed(() =>
  props.columns.length
    ? props.columns
    : Object.keys(props.rows[0] || {}).map((key) => ({ key, label: key })),
);
</script>
<template>
  <div class="table-scroll">
    <table>
      <thead>
        <tr>
          <th
            v-for="column in headings"
            :key="column.key"
            :class="{ numeric: column.type === 'number' }"
            :title="column.definition"
          >
            {{ column.label
            }}<small v-if="column.unit" class="block">{{ column.unit }}</small>
          </th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(row, index) in rows" :key="index">
          <td
            v-for="column in headings"
            :key="column.key"
            :class="{ numeric: column.type === 'number' }"
          >
            {{ formatCell(row[column.key], column) }}
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
