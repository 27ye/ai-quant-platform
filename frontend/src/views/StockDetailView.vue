<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import { fetchIndicators, fetchKline, fetchScore, runBacktest } from '../api/stocks'
import { fetchNews } from '../api/news'
import type {
  BacktestData,
  IndicatorsItem,
  KlineItem,
  NewsItem,
  ScoreData,
} from '../types/api'
import KlineChart from '../components/stock/KlineChart.vue'
import AIReportCard from '../components/ai/AIReportCard.vue'
import ScoreCard from '../components/stock/ScoreCard.vue'
import BacktestPanel from '../components/stock/BacktestPanel.vue'
import NewsList from '../components/stock/NewsList.vue'
import { useHealthStore } from '../stores/health'

const router = useRouter()
const health = useHealthStore()
const stockCode = computed(() => String(router.currentRoute.value.params.code ?? ''))

const kline = ref<KlineItem[]>([])
const indicators = ref<IndicatorsItem[]>([])
const score = ref<ScoreData | null>(null)
const backtest = ref<BacktestData | null>(null)
const news = ref<NewsItem[]>([])
const loading = ref(false)
const loaded = ref(false)
const scoreLoading = ref(true)
const backtestLoading = ref(true)
const newsLoading = ref(true)

// Epoch 机制：切换股票时递增，过期响应直接丢弃
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

const dateRange = computed(() => {
  if (kline.value.length === 0) return ''
  const first = kline.value[0].trade_date
  const last = kline.value[kline.value.length - 1].trade_date
  return `${first} ~ ${last}`
})

async function load() {
  if (!stockCode.value) return
  const currentEpoch = ++epoch.value
  loading.value = true
  loaded.value = false
  kline.value = []
  indicators.value = []
  score.value = null
  backtest.value = null
  news.value = []
  scoreLoading.value = true
  backtestLoading.value = true
  newsLoading.value = true

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
  fetchNews(stockCode.value)
    .then((res) => {
      if (epoch.value !== currentEpoch) return
      news.value = res.data
    })
    .catch(() => undefined)
    .finally(() => {
      if (epoch.value === currentEpoch) newsLoading.value = false
    })
}

watch(stockCode, load, { immediate: true })
onMounted(() => health.refresh())
</script>

<template>
  <main class="dashboard">
    <!-- 股票信息条 -->
    <div class="stock-bar">
      <div class="stock-identity">
        <span class="stock-code">{{ stockCode }}</span>
        <span v-if="dateRange" class="date-range">{{ dateRange }}</span>
        <span v-if="health.acceptanceMode" class="mode-badge">{{ health.acceptanceMode }}</span>
        <span class="v1-badge">V1 冻结演示 · 仅 600519 · 2025-01-02 ~ 2026-08-31</span>
      </div>
      <div v-if="latest" class="stock-quote">
        <span class="price">{{ latest.close.toFixed(2) }}</span>
        <span :class="['change', changeClass]">{{ changeText }}</span>
      </div>
    </div>

    <!-- 主区域：左图表+评分 + 右AI分析 -->
    <div class="main-grid">
      <div class="chart-section">
        <el-card v-loading="loading" shadow="never" class="chart-card">
          <KlineChart
            v-if="loaded && kline.length > 0"
            :items="kline"
            :indicators="indicators"
          />
          <el-empty v-else-if="loaded" description="暂无 K 线数据" />
        </el-card>

        <ScoreCard v-if="score" :data="score" />
        <el-card v-else-if="scoreLoading" shadow="never" class="skeleton-card">
          <el-skeleton :rows="4" animated />
        </el-card>
      </div>

      <div class="ai-section">
        <AIReportCard :stock-code="stockCode" />
      </div>
    </div>

    <!-- 底部：回测 + 新闻（两列） -->
    <div class="bottom-grid">
      <BacktestPanel v-if="backtest" :data="backtest" />
      <el-card v-else-if="backtestLoading" shadow="never" class="skeleton-card">
        <el-skeleton :rows="4" animated />
      </el-card>

      <!-- 新闻：加载完成后始终展示模块，空数组时组件内部显示「暂无新闻」 -->
      <NewsList v-if="!newsLoading" :items="news" />
      <el-card v-else shadow="never" class="skeleton-card">
        <el-skeleton :rows="4" animated />
      </el-card>
    </div>
  </main>
</template>

<style scoped>
.dashboard {
  width: 100%;
  box-sizing: border-box;
  padding: 16px 24px 48px;
}

/* 股票信息条 — 紧凑的水平条 */
.stock-bar {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 14px;
  margin-bottom: 14px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.stock-identity {
  display: flex;
  align-items: baseline;
  gap: 12px;
}

.stock-code {
  font-size: 20px;
  font-weight: 700;
  color: rgba(255, 255, 255, 0.92);
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.02em;
}

.date-range {
  color: rgba(255, 255, 255, 0.38);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.mode-badge {
  padding: 1px 6px;
  border: 1px solid var(--accent, #d4a958);
  border-radius: 3px;
  color: var(--accent, #d4a958);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}

/* V1 冻结演示徽标（详情页同步标注，避免误读为实时行情） */
.v1-badge {
  padding: 2px 10px;
  border: 1px solid rgba(212, 169, 88, 0.4);
  border-radius: 999px;
  background: rgba(212, 169, 88, 0.08);
  color: rgba(212, 169, 88, 0.9);
  font-size: 11px;
  letter-spacing: 0.04em;
}

.stock-quote {
  display: flex;
  align-items: baseline;
  gap: 10px;
}

.price {
  font-size: 28px;
  font-weight: 700;
  color: rgba(255, 255, 255, 0.92);
  font-variant-numeric: tabular-nums;
}

.change {
  font-size: 14px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.change.up {
  color: var(--up, #ff4d4f);
}

.change.down {
  color: var(--down, #00b386);
}

/* 主网格：左(图表+评分) + 右AI分析 */
.main-grid {
  display: grid;
  grid-template-columns: 1fr 380px;
  gap: 14px;
  margin-bottom: 14px;
}

.chart-section {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.chart-card {
  flex: 1;
  background: var(--surface, #14171d);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 8px;
  min-height: 0;
}

.chart-card :deep(.el-card__body) {
  padding: 12px;
  height: 100%;
  box-sizing: border-box;
}

.ai-section {
  min-width: 0;
}

/* 底部网格：回测 + 新闻两列 */
.bottom-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}

.skeleton-card {
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 8px;
}

@media (max-width: 880px) {
  .main-grid {
    grid-template-columns: 1fr;
  }

  .bottom-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 760px) {
  .dashboard {
    padding: 12px 12px 32px;
  }

  .stock-bar {
    flex-direction: column;
    gap: 8px;
  }
}
</style>
