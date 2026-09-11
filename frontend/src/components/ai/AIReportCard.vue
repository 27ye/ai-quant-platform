<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import { analyzeStock } from '../../api/ai'
import type { AIAnalysisData, TrendValue } from '../../types/api'

const props = defineProps<{ stockCode: string }>()

const report = ref<AIAnalysisData | null>(null)
const loading = ref(false)
const failed = ref(false)

// Epoch 机制：切换股票时递增，使在途的 AI 请求过期被丢弃
const epoch = ref(0)

// A 股配色习惯：看涨红、看跌绿
const TREND_LABEL: Record<TrendValue, string> = {
  bullish: '看涨',
  neutral: '中性',
  bearish: '看跌',
}

const trendClass = computed(() => {
  const trend = report.value?.trend
  if (trend === 'bullish') return 'up'
  if (trend === 'bearish') return 'down'
  return ''
})

async function run() {
  const currentEpoch = ++epoch.value
  loading.value = true
  failed.value = false
  report.value = null
  try {
    const res = await analyzeStock(props.stockCode)
    if (epoch.value !== currentEpoch) return
    report.value = res.data
  } catch {
    if (epoch.value !== currentEpoch) return
    failed.value = true
  } finally {
    if (epoch.value === currentEpoch) loading.value = false
  }
}

// 切换股票时重置旧报告并使在途请求过期
watch(
  () => props.stockCode,
  () => {
    epoch.value++
    report.value = null
    failed.value = false
  },
)
</script>

<template>
  <el-card shadow="never" class="ai-card">
    <template #header>
      <div class="card-header">
        <span>AI 投研分析</span>
        <el-button
          v-if="report || failed"
          size="small"
          :disabled="loading"
          @click="run"
        >
          重新分析
        </el-button>
      </div>
    </template>

    <!-- 初始态 -->
    <div v-if="!loading && !report && !failed" class="idle">
      <p>
        基于真实行情、技术指标、量化评分与新闻数据，由大模型生成综合投研分析。过程约需
        10~30 秒。
      </p>
      <el-button type="primary" @click="run">开始 AI 分析</el-button>
    </div>

    <!-- 加载态 -->
    <div v-else-if="loading">
      <el-skeleton :rows="6" animated />
      <p class="loading-hint">大模型正在读取数据并生成分析，请稍候…</p>
    </div>

    <!-- 失败态 -->
    <div v-else-if="failed">
      <el-result icon="error" title="分析失败" sub-title="请稍后重试，或检查后端 AI 服务状态">
        <template #extra>
          <el-button type="primary" @click="run">重试</el-button>
        </template>
      </el-result>
    </div>

    <!-- 报告 -->
    <div v-else-if="report" class="report">
      <div class="verdict">
        <span class="verdict-label">AI 观点</span>
        <span :class="['verdict-value', trendClass]">
          {{ TREND_LABEL[report.trend] }}
        </span>
        <span class="verdict-divider" aria-hidden="true"></span>
        <span class="score-chip">
          <span class="chip-label">评分</span>
          <strong>{{ report.quant_score ?? '—' }}</strong>
          <span class="chip-total">/ 100</span>
        </span>
        <span class="model">{{ report.model_name }}</span>
      </div>

      <p class="lede">{{ report.summary }}</p>

      <section class="analysis-block">
        <h4>技术面</h4>
        <p>{{ report.technical_analysis }}</p>
      </section>
      <section class="analysis-block">
        <h4>量化面</h4>
        <p>{{ report.quant_analysis }}</p>
      </section>
      <section class="analysis-block">
        <h4>消息面</h4>
        <p>{{ report.news_analysis }}</p>
      </section>

      <div class="two-col">
        <section class="col">
          <h4>优势</h4>
          <ul class="adv-list">
            <li v-for="item in report.advantages" :key="item">{{ item }}</li>
          </ul>
        </section>
        <section class="col">
          <h4>风险</h4>
          <ul class="risk-list">
            <li v-for="item in report.risks" :key="item">{{ item }}</li>
          </ul>
        </section>
      </div>

      <section class="conclusion">
        <h4>结论</h4>
        <p>{{ report.conclusion }}</p>
        <span class="risk-badge">风险提示：以上内容由 AI 分析得出，不构成投资建议</span>
      </section>
    </div>
  </el-card>
</template>

<style scoped>
.ai-card {
  margin-bottom: 16px;
  display: flex;
  flex-direction: column;
}

.ai-card :deep(.el-card__body) {
  flex: 1;
  min-height: 0;
  max-height: calc(100vh - 220px);
  overflow-y: auto;
}

.ai-card :deep(.el-card__body::-webkit-scrollbar) {
  width: 6px;
}

.ai-card :deep(.el-card__body::-webkit-scrollbar-track) {
  background: transparent;
}

.ai-card :deep(.el-card__body::-webkit-scrollbar-thumb) {
  background: rgba(255, 255, 255, 0.15);
  border-radius: 3px;
}

.ai-card :deep(.el-card__body::-webkit-scrollbar-thumb:hover) {
  background: rgba(255, 255, 255, 0.25);
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: 600;
}

.idle p {
  color: var(--text-sub);
  margin-bottom: 16px;
}

.loading-hint {
  margin: 16px 0 0;
  color: var(--text-sub);
  font-size: 13px;
}

/* 观点判定行：单行紧凑 */
.verdict {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 10px;
  padding-bottom: 12px;
  margin-bottom: 14px;
  border-bottom: 1px solid var(--border, rgba(255, 255, 255, 0.06));
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
  color: var(--up, #ff4d4f);
}

.verdict-value.down {
  color: var(--down, #00b386);
}

.verdict-divider {
  align-self: center;
  width: 1px;
  height: 12px;
  background: var(--border-strong, rgba(255, 255, 255, 0.16));
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
  color: rgba(255, 255, 255, 0.85);
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
  border-top: 1px solid var(--border, rgba(255, 255, 255, 0.06));
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
  background: rgba(255, 255, 255, 0.28);
}

.adv-list li::before {
  background: var(--down, #00b386);
}

.risk-list li::before {
  background: var(--up, #ff4d4f);
}

.conclusion {
  border-top: 1px solid var(--border, rgba(255, 255, 255, 0.06));
  padding-top: 14px;
  margin-bottom: 0;
}

.conclusion p {
  color: rgba(255, 255, 255, 0.85);
  font-size: 13px;
  line-height: 1.7;
  border-left: 2px solid var(--accent, #d4a958);
  padding-left: 10px;
}

.risk-badge {
  display: inline-block;
  margin-top: 10px;
  padding: 3px 8px;
  border: 1px solid var(--border-strong, rgba(255, 255, 255, 0.16));
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
