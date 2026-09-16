<script setup lang="ts">
// AI 报告正文的纯展示组件：新生成（AIReportCard）与历史详情（AIReportDetailView）共用
import { computed } from 'vue'

import type { AIAnalysisData } from '../../types/api'
import { TREND_LABEL } from '../../utils/format'

const props = defineProps<{ data: AIAnalysisData }>()

const trendClass = computed(() => {
  const trend = props.data.trend
  if (trend === 'bullish') return 'up'
  if (trend === 'bearish') return 'down'
  return ''
})
</script>

<template>
  <div class="report">
    <div class="verdict">
      <span class="verdict-label">AI 观点</span>
      <span :class="['verdict-value', trendClass]">
        {{ TREND_LABEL[data.trend] }}
      </span>
      <span class="verdict-divider" aria-hidden="true"></span>
      <span class="score-chip">
        <span class="chip-label">评分</span>
        <strong>{{ data.quant_score ?? '—' }}</strong>
        <span class="chip-total">/ 100</span>
      </span>
      <span class="model">{{ data.model_name }}</span>
    </div>

    <p class="lede">{{ data.summary }}</p>

    <section class="analysis-block">
      <h4>技术面</h4>
      <p>{{ data.technical_analysis }}</p>
    </section>
    <section class="analysis-block">
      <h4>量化面</h4>
      <p>{{ data.quant_analysis }}</p>
    </section>
    <section class="analysis-block">
      <h4>消息面</h4>
      <p>{{ data.news_analysis }}</p>
    </section>

    <div class="two-col">
      <section class="col">
        <h4>优势</h4>
        <ul class="adv-list">
          <li v-for="item in data.advantages" :key="item">{{ item }}</li>
        </ul>
      </section>
      <section class="col">
        <h4>风险</h4>
        <ul class="risk-list">
          <li v-for="item in data.risks" :key="item">{{ item }}</li>
        </ul>
      </section>
    </div>

    <section class="conclusion">
      <h4>结论</h4>
      <p>{{ data.conclusion }}</p>
      <span class="risk-badge">风险提示：以上内容由 AI 分析得出，不构成投资建议</span>
    </section>
  </div>
</template>

<style scoped>
/* 观点判定行：单行紧凑 */
.verdict {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 10px;
  padding-bottom: 12px;
  margin-bottom: 14px;
  border-bottom: 1px solid var(--border);
}

.verdict-label {
  color: var(--text-faint);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.verdict-value {
  font-size: 18px;
  font-weight: 700;
  line-height: 1;
}

.verdict-value.up {
  color: var(--up);
}

.verdict-value.down {
  color: var(--down);
}

.verdict-divider {
  align-self: center;
  width: 1px;
  height: 12px;
  background: var(--border-strong);
}

.score-chip {
  display: inline-flex;
  align-items: baseline;
  gap: 3px;
}

.chip-label {
  color: var(--text-faint);
  font-size: 11px;
}

.score-chip strong {
  color: var(--text-main);
  font-size: 16px;
  font-variant-numeric: tabular-nums;
}

.chip-total {
  color: var(--text-faint);
  font-size: 11px;
}

.model {
  margin-left: auto;
  color: var(--text-faint);
  font-size: 11px;
}

/* 导语式摘要 */
.lede {
  margin: 0 0 16px;
  color: var(--text-main);
  font-size: 14px;
  line-height: 1.75;
}

/* 三个分析维度纵向排列 */
.analysis-block {
  margin-bottom: 14px;
}

.analysis-block h4 {
  margin: 0 0 4px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-faint);
  letter-spacing: 0.04em;
}

.analysis-block p {
  margin: 0;
  color: var(--text-sub);
  font-size: 13px;
  line-height: 1.7;
}

section {
  margin-bottom: 14px;
}

section h4 {
  margin: 0 0 4px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-faint);
  letter-spacing: 0.04em;
}

section p {
  margin: 0;
  line-height: 1.7;
  color: var(--text-sub);
  font-size: 13px;
}

.two-col {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--border);
}

.two-col ul {
  list-style: none;
  margin: 0;
  padding: 0;
  line-height: 1.7;
  color: var(--text-sub);
  font-size: 12.5px;
}

.two-col ul li {
  position: relative;
  padding-left: 12px;
  margin-bottom: 4px;
}

.two-col ul li::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0.7em;
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: var(--text-faint);
}

.adv-list li::before {
  background: var(--down);
}

.risk-list li::before {
  background: var(--up);
}

.conclusion {
  border-top: 1px solid var(--border);
  padding-top: 14px;
  margin-bottom: 0;
}

.conclusion p {
  color: var(--text-main);
  font-size: 13px;
  line-height: 1.7;
  border-left: 2px solid var(--accent);
  padding-left: 10px;
}

.risk-badge {
  display: inline-block;
  margin-top: 10px;
  padding: 3px 8px;
  border: 1px solid var(--border-strong);
  border-radius: 3px;
  color: var(--text-faint);
  font-size: 11px;
}

@media (max-width: 760px) {
  .two-col {
    grid-template-columns: 1fr;
  }
}
</style>
