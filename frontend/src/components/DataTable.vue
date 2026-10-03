<script setup>
defineProps({ rows: { type: Array, required: true } });
</script>
<template>
  <div class="table-scroll">
    <table>
      <thead>
        <tr>
          <th v-for="key in Object.keys(rows[0] || {})" :key="key">
            {{ key }}
          </th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(row, index) in rows" :key="index">
          <td v-for="key in Object.keys(rows[0] || {})" :key="key">
            {{
              row[key] === null
                ? "—"
                : typeof row[key] === "object"
                  ? JSON.stringify(row[key])
                  : row[key]
            }}
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
