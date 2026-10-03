<script setup>
import { computed, defineAsyncComponent } from "vue";
import {
  aiStatuses,
  evidenceItems,
  resultColumns,
  aiChart,
  evidenceRange,
} from "../utils/ai.js";
import { number } from "../utils/format.js";
import { renderAnswer } from "../utils/markdown.js";
import DataTable from "./DataTable.vue";
import Icon from "./Icon.vue";

const Chart = defineAsyncComponent(() => import("./Chart.vue"));
const props = defineProps({ result: { type: Object, required: true } });
defineEmits(["choose"]);
const status = computed(() => aiStatuses[props.result.status] || aiStatuses.ok);
const answer = computed(() => renderAnswer(props.result.answer));
const columns = computed(() => resultColumns(props.result));
const samples = computed(() => evidenceItems(props.result.evidence));
const chart = computed(() => aiChart(props.result));
const evidence = computed(() => props.result.evidence);
const range = computed(() => evidenceRange(evidence.value));
</script>
<template>
  <section class="panel ai-analysis-panel" aria-labelledby="ai-result-heading">
    <header class="panel-header">
      <h2 id="ai-result-heading"><Icon name="ai" />分析结果</h2>
      <span class="ai-status" :class="status.className" role="status">{{
        status.label
      }}</span>
    </header>
    <p v-if="result.question" class="ai-question">{{ result.question }}</p>
    <div
      v-if="result.status === 'needs_clarification' && result.clarification"
      class="ai-clarification"
    >
      <h3>{{ result.clarification.question }}</h3>
      <p>选择一个条件填入问题，确认后再发送。</p>
      <div class="ai-suggestions">
        <button
          v-for="choice in result.clarification.choices"
          :key="choice.prompt"
          class="button secondary small"
          @click="$emit('choose', choice.prompt)"
        >
          {{ choice.label }}<Icon name="arrow" />
        </button>
      </div>
    </div>
    <div v-if="evidence" class="ai-evidence">
      <div class="ai-scope">
        <strong>时间筛选</strong><span>{{ range.requested }}</span
        ><span v-if="evidence.grain" class="tag">{{ evidence.grain }}</span>
      </div>
      <p class="ai-sample-range">确认赛程样本：{{ range.samples }}</p>
      <dl v-if="samples.length" class="ai-sample-grid">
        <div v-for="sample in samples" :key="sample.key">
          <dt>{{ sample.label }}</dt>
          <dd>
            {{ sample.value }}<small>{{ sample.unit }}</small>
          </dd>
        </div>
      </dl>
      <p
        v-if="
          evidence.scheduled_matches != null ||
          evidence.updated_date_matches != null ||
          evidence.unknown_date_matches != null
        "
        class="ai-date-quality"
      >
        日期口径：<span v-if="evidence.scheduled_matches != null"
          >开赛日期 {{ number(evidence.scheduled_matches) }} 场</span
        ><span v-if="evidence.updated_date_matches != null"
          >源更新时间 {{ number(evidence.updated_date_matches) }} 场</span
        ><span v-if="evidence.unknown_date_matches != null"
          >日期未记录 {{ number(evidence.unknown_date_matches) }} 场</span
        >
      </p>
    </div>
    <div v-if="result.assumptions?.length" class="ai-assumptions">
      <h3>本次统计口径</h3>
      <ul>
        <li v-for="assumption in result.assumptions" :key="assumption">
          {{ assumption }}
        </li>
      </ul>
    </div>
    <div v-if="result.answer" class="markdown ai-answer" v-html="answer"></div>
    <div v-if="chart" class="ai-chart-section">
      <h3>数据图表</h3>
      <Chart
        :option="chart.option"
        label="本次 AI 查询结果图表"
        :height="320"
      />
      <p class="muted small-text">
        缺失指标留空。<span v-if="chart.displayed < chart.total"
          >图表展示前 {{ chart.displayed }} 条，完整
          {{ chart.total }} 条结果见下表。</span
        >
      </p>
    </div>
    <div v-if="result.data?.length" class="ai-data-section">
      <div class="ai-subheading">
        <h3>查询数据</h3>
        <span class="muted small-text"
          >返回 {{ number(result.data.length) }} 条</span
        >
      </div>
      <DataTable :rows="result.data" :columns="columns" />
      <details
        v-if="columns.some((column) => column.definition)"
        class="ai-definitions"
      >
        <summary>查看指标定义</summary>
        <dl>
          <template
            v-for="column in columns.filter((column) => column.definition)"
            :key="column.key"
            ><dt>{{ column.label }}</dt>
            <dd>{{ column.definition }}</dd></template
          >
        </dl>
      </details>
    </div>
    <p v-else-if="result.status === 'empty'" class="ai-empty-note">
      当前筛选范围没有匹配记录。可以调整日期、实体名称或最低样本数后再查询。
    </p>
    <details v-if="result.sql" class="ai-sql">
      <summary>查看 SQL 与查询证据</summary>
      <p v-if="evidence" class="muted small-text">
        数据返回
        {{ number(evidence.returned_rows ?? result.data?.length) }} 条<span
          v-if="evidence.repaired"
        >
          · 已修正一次查询</span
        >
      </p>
      <pre><code>{{ result.sql }}</code></pre>
    </details>
    <div v-if="result.followups?.length" class="ai-followups">
      <h3>继续分析</h3>
      <p class="muted small-text">
        点击填入追问，确认后发送。{{
          result.context?.plan ? "会沿用本次统计条件。" : ""
        }}
      </p>
      <div class="ai-suggestions">
        <button
          v-for="followup in result.followups"
          :key="followup.prompt"
          class="button secondary small"
          @click="$emit('choose', followup.prompt)"
        >
          {{ followup.label }}<Icon name="arrow" />
        </button>
      </div>
    </div>
  </section>
</template>
