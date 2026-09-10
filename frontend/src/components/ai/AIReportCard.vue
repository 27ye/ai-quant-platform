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
          <span class="chip-label">量化评分</span>
          <strong>{{ report.quant_score ?? '—' }}</strong>
          <span class="chip-total">/ 100</span>
        </span>
        <span class="model">{{ report.model_name }}</span>
      </div>

      <p class="lede">{{ report.summary }}</p>

      <div class="analysis-grid">
        <section>
          <h4>技术面</h4>
          <p>{{ report.technical_analysis }}</p>
        </section>
        <section>
          <h4>量化面</h4>
          <p>{{ report.quant_analysis }}</p>
        </section>
        <section>
          <h4>消息面</h4>
          <p>{{ report.news_analysis }}</p>
        </section>
      </div>

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

/* 观点判定行：头条式排版 */
.verdict {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 12px;
  margin-bottom: 14px;
}

.verdict-label {
  color: var(--text-faint);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.06em;
}

.verdict-value {
  font-size: 22px;
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
  height: 14px;
  background: var(--border-strong, rgba(255, 255, 255, 0.16));
}

.score-chip {
  display: inline-flex;
  align-items: baseline;
  gap: 4px;
}

.chip-label {
  color: var(--text-faint);
  font-size: 12px;
}

.score-chip strong {
  color: var(--text-main);
  font-size: 20px;
}

.chip-total {
  color: var(--text-faint);
  font-size: 12px;
}

.model {
  margin-left: auto;
  color: var(--text-faint);
  font-size: 12px;
}

/* 导语式摘要 */
.lede {
  margin: 0 0 18px;
  color: rgba(255, 255, 255, 0.85);
  font-size: 15px;
  line-height: 1.8;
}

/* 三个分析维度并排 */
.analysis-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 20px;
  margin-bottom: 18px;
}

.analysis-grid h4 {
  margin: 0 0 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-sub);
}

.analysis-grid p {
  margin: 0;
  color: var(--text-sub);
  font-size: 13px;
  line-height: 1.7;
}

section {
  margin-bottom: 16px;
}

/* 层级靠字号字重区分，不用颜色 */
section h4 {
  margin: 0 0 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-sub);
}

section p {
  margin: 0;
  line-height: 1.75;
  color: var(--text-sub);
}

.two-col {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.two-col ul {
  list-style: none;
  margin: 0;
  padding: 0;
  line-height: 1.9;
  color: var(--text-sub);
}

.two-col ul li {
  position: relative;
  padding-left: 14px;
}

/* 优势/风险用小圆点区分，不染标题 */
.two-col ul li::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0.72em;
  width: 5px;
  height: 5px;
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
  border-top: 1px solid var(--border, rgba(255, 255, 255, 0.07));
  padding-top: 14px;
  margin-bottom: 0;
}

.conclusion p {
  color: rgba(255, 255, 255, 0.85);
  font-size: 14px;
  border-left: 2px solid var(--accent, #d4a958);
  padding-left: 12px;
}

.risk-badge {
  display: inline-block;
  margin-top: 10px;
  padding: 4px 10px;
  border: 1px solid var(--border-strong, rgba(255, 255, 255, 0.16));
  border-radius: 4px;
  color: var(--text-faint);
  font-size: 12px;
}

@media (max-width: 900px) {
  .analysis-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 760px) {
  .two-col {
    grid-template-columns: 1fr;
  }
}
</style>
