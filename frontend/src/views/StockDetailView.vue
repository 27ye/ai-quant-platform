<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import {
  fetchDataStatus,
  fetchIndicators,
  fetchKline,
  fetchScore,
  fetchStockInfo,
} from '../api/stocks'
import type {
  DataStatus,
  IndicatorsItem,
  KlineItem,
  ScoreData,
} from '../types/api'
import KlineChart from '../components/stock/KlineChart.vue'
import AIReportCard from '../components/ai/AIReportCard.vue'
import ScoreCard from '../components/stock/ScoreCard.vue'
import BacktestPanel from '../components/stock/BacktestPanel.vue'
import DataStatusBadge from '../components/stock/DataStatusBadge.vue'
import WatchlistCard from '../components/stock/WatchlistCard.vue'
import { useAppContext } from '../stores/appContext'
import { useHealthStore } from '../stores/health'

const router = useRouter()
const health = useHealthStore()
const appContext = useAppContext()
// / 路由没有 :code 参数，回退到最近访问的股票（冻结演示默认 600519）
const stockCode = computed(
  () => String(router.currentRoute.value.params.code ?? '') || appContext.stockCode,
)

const kline = ref<KlineItem[]>([])
const indicators = ref<IndicatorsItem[]>([])
const score = ref<ScoreData | null>(null)
const dataStatus = ref<DataStatus | null>(null)
const stockName = ref('')
const loading = ref(false)
const loaded = ref(false)
const klineFailed = ref(false)
const scoreLoading = ref(true)
const scoreFailed = ref(false)

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
  // 登记最近访问的股票，供侧栏导航拼链接
  appContext.setStockCode(stockCode.value)
  loading.value = true
  loaded.value = false
  klineFailed.value = false
  kline.value = []
  indicators.value = []
  score.value = null
  dataStatus.value = null
  scoreLoading.value = true
  scoreFailed.value = false
  stockName.value = ''

  // 非关键请求统一跳过拦截器弹窗，错误由各区域自行展示（避免一次进页面连弹多条 toast）
  const silent = { skipErrorHandler: true }

  try {
    const klineRes = await fetchKline(stockCode.value)
    if (epoch.value !== currentEpoch) return
    kline.value = klineRes.data
    loaded.value = true
    fetchIndicators(stockCode.value, silent)
      .then((res) => {
        if (epoch.value !== currentEpoch) return
        indicators.value = res.data
      })
      .catch(() => undefined)
  } catch {
    if (epoch.value !== currentEpoch) return
    klineFailed.value = true
  } finally {
    if (epoch.value === currentEpoch) loading.value = false
  }

  fetchScore(stockCode.value, silent)
    .then((res) => {
      if (epoch.value !== currentEpoch) return
      score.value = res.data
    })
    .catch(() => {
      if (epoch.value !== currentEpoch) return
      scoreFailed.value = true
    })
    .finally(() => {
      if (epoch.value === currentEpoch) scoreLoading.value = false
    })
  // 数据状态徽标：非关键路径，失败静默不展示
  fetchDataStatus(stockCode.value, silent)
    .then((res) => {
      if (epoch.value !== currentEpoch) return
      dataStatus.value = res.data
    })
    .catch(() => undefined)

  // 股票名称：本地缓存/冻结兜底立即显示，再用详情接口（实时 provider）补全；失败静默
  stockName.value = appContext.resolveStockName(stockCode.value)
  fetchStockInfo(stockCode.value, silent)
    .then((res) => {
      if (epoch.value !== currentEpoch) return
      stockName.value = res.data.stock_name
      // 顺手登记 code→name，自选等功能零额外请求取名称
      appContext.rememberStockNames([
        { stock_code: res.data.stock_code, stock_name: res.data.stock_name },
      ])
    })
    .catch(() => {
      // 实时源持续不可用时退回缓存/兜底名称，页头不留空
      if (epoch.value !== currentEpoch) return
      stockName.value = appContext.resolveStockName(stockCode.value)
    })
}

watch(stockCode, load, { immediate: true })
onMounted(() => health.refresh())
</script>

<template>
  <main class="dashboard">
    <!-- 页头：与其他页面一致的标题结构 -->
    <header class="page-header">
      <div class="header-left">
        <h1 class="page-title">工作台</h1>
        <span class="stock-chip">
          {{ stockCode }}<template v-if="stockName"> · {{ stockName }}</template>
        </span>
      </div>
      <div v-if="latest" class="stock-quote">
        <span class="price">{{ latest.close.toFixed(2) }}</span>
        <span :class="['change', changeClass]">{{ changeText }}</span>
      </div>
    </header>

    <!-- 股票元信息条 -->
    <div class="stock-bar">
      <span v-if="dateRange" class="date-range">{{ dateRange }}</span>
      <span v-if="health.acceptanceMode" class="mode-badge">{{ health.acceptanceMode }}</span>
      <DataStatusBadge v-if="dataStatus" :status="dataStatus" />
    </div>

    <!-- 本地自选（V3 F1：紧凑条，位于股票信息条下方） -->
    <WatchlistCard :stock-code="stockCode" />

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
          <div v-else-if="klineFailed" class="region-error">
            <el-result icon="warning" title="K 线加载失败" sub-title="数据源暂时不可用，请稍后重试">
              <template #extra>
                <el-button type="primary" @click="load">重试</el-button>
              </template>
            </el-result>
          </div>
        </el-card>

        <ScoreCard v-if="score" :data="score" />
        <el-card v-else-if="scoreLoading" shadow="never" class="skeleton-card">
          <el-skeleton :rows="4" animated />
        </el-card>
        <el-card v-else-if="scoreFailed" shadow="never" class="skeleton-card">
          <div class="region-error">
            <el-result icon="warning" title="评分加载失败" sub-title="数据源暂时不可用，请稍后重试">
              <template #extra>
                <el-button type="primary" @click="load">重试</el-button>
              </template>
            </el-result>
          </div>
        </el-card>
      </div>

      <div class="ai-section">
        <AIReportCard :stock-code="stockCode" />
      </div>
    </div>

    <!-- 底部：回测面板（自包含数据逻辑：v1 快速 + v2 参数化表单）；新闻已拆到独立页 /stock/:code/news -->
    <BacktestPanel :stock-code="stockCode" />
  </main>
</template>

<style scoped>
.dashboard {
  width: 100%;
  box-sizing: border-box;
  padding: 16px 24px 48px;
}

/* 页头：与新闻/回测等页面同一结构 */
.page-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  padding-bottom: 14px;
  margin-bottom: 12px;
  border-bottom: 1px solid var(--border);
}

.header-left {
  display: flex;
  align-items: baseline;
  gap: 12px;
  min-width: 0;
}

.page-title {
  margin: 0;
  font-size: 18px;
  font-weight: 700;
  color: var(--text-main);
  letter-spacing: 0.01em;
}

.stock-chip {
  font-size: 12px;
  color: var(--text-faint);
  font-variant-numeric: tabular-nums;
}

/* 股票元信息条 — 页头下的一行小字 */
.stock-bar {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 14px;
}

.date-range {
  color: var(--text-faint);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.mode-badge {
  padding: 1px 6px;
  border: 1px solid var(--accent);
  border-radius: 3px;
  color: var(--accent);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}

/* 数据状态徽标样式在 DataStatusBadge 组件内 */

.stock-quote {
  display: flex;
  align-items: baseline;
  gap: 10px;
}

.price {
  font-size: 28px;
  font-weight: 700;
  color: var(--text-main);
  font-variant-numeric: tabular-nums;
}

.change {
  font-size: 14px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.change.up {
  color: var(--up);
}

.change.down {
  color: var(--down);
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
  min-height: 0;
}

.chart-card :deep(.el-card__body) {
  padding: 12px;
  height: 100%;
  box-sizing: border-box;
}

/* 区域级失败态：压缩 el-result 默认留白，避免撑高卡片 */
.region-error :deep(.el-result) {
  padding: 24px 12px;
}

.region-error :deep(.el-result__icon svg) {
  width: 40px;
  height: 40px;
}

.region-error :deep(.el-result__title p) {
  font-size: 14px;
}

.region-error :deep(.el-result__subtitle p) {
  font-size: 12px;
}

.ai-section {
  min-width: 0;
}

@media (max-width: 880px) {
  .main-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 760px) {
  .dashboard {
    padding: 12px 12px 32px;
  }

  .page-header {
    flex-wrap: wrap;
  }

  .stock-bar {
    gap: 8px;
  }
}
</style>
