<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import { fetchIndicators, fetchKline, fetchScore, runBacktest } from '../api/stocks'
import type { BacktestData, IndicatorsItem, KlineItem, ScoreData } from '../types/api'
import KlineChart from '../components/stock/KlineChart.vue'
import AIReportCard from '../components/ai/AIReportCard.vue'
import ScoreCard from '../components/stock/ScoreCard.vue'
import BacktestPanel from '../components/stock/BacktestPanel.vue'
import { useHealthStore } from '../stores/health'

const router = useRouter()
const health = useHealthStore()
const stockCode = computed(() => String(router.currentRoute.value.params.code ?? ''))

const kline = ref<KlineItem[]>([])
const indicators = ref<IndicatorsItem[]>([])
const score = ref<ScoreData | null>(null)
const backtest = ref<BacktestData | null>(null)
const loading = ref(false)
const loaded = ref(false)
const scoreLoading = ref(true)
const backtestLoading = ref(true)

// Epoch 机制：切换股票时递增，过期响应直接丢弃，避免旧结果串入新股票
const epoch = ref(0)

const latest = computed(() =>
  kline.value.length > 0 ? kline.value[kline.value.length - 1] : null,
)
const lastChange = computed(() => latest.value?.change_pct ?? 0)
const changeText = computed(() => {
  const sign = lastChange.value > 0 ? '▲' : lastChange.value < 0 ? '▼' : ''
  const value = `${(lastChange.value * 100).toFixed(2)}%`
  return `${sign} ${value}`.trim()
})
const changeClass = computed(() =>
  lastChange.value > 0 ? 'up' : lastChange.value < 0 ? 'down' : '',
)

// 样本区间标识（D 联调要求：显示数据日期范围）
const dateRange = computed(() => {
  if (kline.value.length === 0) return ''
  const first = kline.value[0].trade_date
  const last = kline.value[kline.value.length - 1].trade_date
  return `${first} ~ ${last}`
})

async function load() {
  if (!stockCode.value) return
  // 递增 epoch，使所有在途请求过期
  const currentEpoch = ++epoch.value
  loading.value = true
  loaded.value = false
  // 立即清空旧数据，避免新股票页面闪现上一只股票的内容
  kline.value = []
  indicators.value = []
  score.value = null
  backtest.value = null
  scoreLoading.value = true
  backtestLoading.value = true

  try {
    const klineRes = await fetchKline(stockCode.value)
    if (epoch.value !== currentEpoch) return
    kline.value = klineRes.data
    loaded.value = true
    fetchIndicators(stockCode.value)
      .then((res) => {
        if (epoch.value !== currentEpoch) return
        indicators.value = res.data
      })
      .catch(() => undefined)
  } catch {
    if (epoch.value !== currentEpoch) return
  } finally {
    if (epoch.value === currentEpoch) loading.value = false
  }

  fetchScore(stockCode.value)
    .then((res) => {
      if (epoch.value !== currentEpoch) return
      score.value = res.data
    })
    .catch(() => undefined)
    .finally(() => {
      if (epoch.value === currentEpoch) scoreLoading.value = false
    })
  runBacktest(stockCode.value)
    .then((res) => {
      if (epoch.value !== currentEpoch) return
      backtest.value = res.data
    })
    .catch(() => undefined)
    .finally(() => {
      if (epoch.value === currentEpoch) backtestLoading.value = false
    })
}

watch(stockCode, load, { immediate: true })

// 进入详情页时静默刷新健康检查，获取验收模式（D 联调用）
onMounted(() => health.refresh())
</script>

<template>
  <main class="shell">
    <section class="workspace">
      <header class="detail-header">
        <el-button text @click="router.back()">← 返回</el-button>
        <div class="title">
          <h2>{{ stockCode }} 日 K 线（前复权）</h2>
          <span v-if="health.acceptanceMode" class="mode-badge">{{ health.acceptanceMode }}</span>
          <span v-if="dateRange" class="date-range">{{ dateRange }}</span>
          <div v-if="latest" class="quote">
            <span class="price">{{ latest.close.toFixed(2) }}</span>
            <span :class="['change', changeClass]">{{ changeText }}</span>
            <span class="date">{{ latest.trade_date }}</span>
          </div>
        </div>
      </header>

      <el-card v-loading="loading" shadow="never" class="card-lift chart-card">
        <KlineChart
          v-if="loaded && kline.length > 0"
          :items="kline"
          :indicators="indicators"
        />
        <el-empty v-else-if="loaded" description="暂无 K 线数据" />
      </el-card>

      <AIReportCard :stock-code="stockCode" />

      <div class="bottom-grid">
        <ScoreCard v-if="score" :data="score" />
        <el-card v-else-if="scoreLoading" shadow="never" class="card-lift">
          <el-skeleton :rows="4" animated />
        </el-card>

        <BacktestPanel v-if="backtest" :data="backtest" />
        <el-card v-else-if="backtestLoading" shadow="never" class="card-lift">
          <el-skeleton :rows="4" animated />
        </el-card>
      </div>
    </section>
  </main>
</template>

<style scoped>
.detail-header {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 18px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--border, rgba(255, 255, 255, 0.07));
}

.title {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 16px;
}

.title h2 {
  margin: 0;
}

.date-range {
  color: var(--text-faint);
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}

.mode-badge {
  padding: 2px 8px;
  border: 1px solid var(--accent, #d4a958);
  border-radius: 4px;
  color: var(--accent, #d4a958);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}

.quote {
  display: flex;
  align-items: baseline;
  gap: 10px;
}

.price {
  font-size: 30px;
  font-weight: 700;
  color: var(--text-main);
}

.change {
  font-size: 15px;
  font-weight: 700;
}

.change.up {
  color: var(--up);
}

.change.down {
  color: var(--down);
}

.date {
  color: var(--text-faint);
  font-size: 13px;
}

.chart-card {
  margin-bottom: 16px;
}

.bottom-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

@media (max-width: 900px) {
  .bottom-grid {
    grid-template-columns: 1fr;
  }
}
</style>
