<script setup lang="ts">
// A3：回测历史详情（/backtests/:id）
// 只读 GET /backtests/{id}，回放保存时快照，不重算；未知 ID → 404 + 40005
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { AxiosError } from 'axios'

import { fetchBacktestDetail } from '../api/backtests'
import type { BacktestDetail } from '../types/api'
import ReturnCurveChart from '../components/stock/ReturnCurveChart.vue'
import { formatDateTime } from '../utils/format'

const route = useRoute()
const router = useRouter()
const backtestId = computed(() => Number(route.params.id))

const detail = ref<BacktestDetail | null>(null)
const loading = ref(true)
const failed = ref(false)
const notFound = ref(false)

// 过期请求防护（同 StockDetailView 的 epoch 模式）
const epoch = ref(0)

async function load() {
  const currentEpoch = ++epoch.value
  if (!Number.isInteger(backtestId.value) || backtestId.value <= 0) {
    loading.value = false
    notFound.value = true
    return
  }
  loading.value = true
  failed.value = false
  notFound.value = false
  detail.value = null
  try {
    const res = await fetchBacktestDetail(backtestId.value)
    if (epoch.value !== currentEpoch) return
    detail.value = res.data
  } catch (error) {
    if (epoch.value !== currentEpoch) return
    // 契约：未知 ID 返回 HTTP 404 + code=40005（backtest not found）
    if (error instanceof AxiosError && error.response?.status === 404) {
      notFound.value = true
    } else {
      failed.value = true
    }
  } finally {
    if (epoch.value === currentEpoch) loading.value = false
  }
}

watch(backtestId, load, { immediate: true })

const isMissing = computed(() => detail.value?.snapshot_status === 'missing')

const METRICS = [
  { key: 'total_return', label: '总收益', kind: 'percent' },
  { key: 'annual_return', label: '年化收益', kind: 'percent' },
  { key: 'max_drawdown', label: '最大回撤', kind: 'percent' },
  { key: 'sharpe_ratio', label: '夏普率', kind: 'decimal' },
  { key: 'win_rate', label: '胜率', kind: 'percent' },
  { key: 'benchmark_return', label: '基准收益', kind: 'percent' },
  { key: 'trade_count', label: '往返次数', kind: 'integer' },
  { key: 'order_count', label: '成交笔数', kind: 'integer' },
] as const

function formatMetric(kind: 'percent' | 'decimal' | 'integer', value: number | null): string {
  if (value == null) return '—'
  if (kind === 'percent') {
    const sign = value > 0 ? '+' : ''
    return `${sign}${(value * 100).toFixed(2)}%`
  }
  if (kind === 'decimal') return value.toFixed(2)
  return String(value)
}

function metricClass(value: number | null): string {
  if (value == null) return ''
  if (value > 0) return 'up'
  if (value < 0) return 'down'
  return ''
}

// 生效参数（白名单随策略：MA 五字段 / MACD 六字段，按存在字段展示）
const paramRows = computed(() => {
  const p = detail.value?.effective_parameters as Record<string, number> | null | undefined
  if (!p) return []
  const rows: Array<{ label: string; value: string }> = []
  if (p.ma_short_period != null) rows.push({ label: '短均线', value: `${p.ma_short_period} 日` })
  if (p.ma_long_period != null) rows.push({ label: '长均线', value: `${p.ma_long_period} 日` })
  if (p.macd_fast_period != null) {
    rows.push({ label: 'MACD 快线', value: `${p.macd_fast_period} 日` })
  }
  if (p.macd_slow_period != null) {
    rows.push({ label: 'MACD 慢线', value: `${p.macd_slow_period} 日` })
  }
  if (p.macd_signal_period != null) {
    rows.push({ label: 'MACD 信号线', value: `${p.macd_signal_period} 日` })
  }
  rows.push({ label: '初始资金', value: p.initial_cash.toLocaleString() })
  rows.push({ label: '交易成本', value: `${(p.transaction_cost * 100).toFixed(3)}%` })
  rows.push({ label: '滑点', value: `${(p.slippage * 100).toFixed(3)}%` })
  return rows
})

// 成交记录表
const hasTrades = computed(() => (detail.value?.trades?.length ?? 0) > 0)

function formatPnl(value: number | null): string {
  if (value == null) return '—'
  const sign = value > 0 ? '+' : ''
  return `${sign}${value.toFixed(2)}`
}

function formatPnlPct(value: number | null): string {
  if (value == null) return '—'
  const sign = value > 0 ? '+' : ''
  return `${sign}${(value * 100).toFixed(2)}%`
}

// 数据元信息：frame_digest 与 c_data_hash 是两个不同的哈希，分开展示
const metaRows = computed(() => {
  const meta = detail.value?.data_meta
  if (!meta) return []
  const short = (hash?: string | null) =>
    hash ? `${hash.slice(0, 8)}…${hash.slice(-8)}` : '—'
  const rows: Array<{ label: string; value: string }> = []
  if (meta.actual_start_date) {
    rows.push({
      label: '实际区间',
      value: `${meta.actual_start_date} ~ ${meta.actual_end_date ?? '—'}`,
    })
  }
  if (meta.rows != null) rows.push({ label: '行情行数', value: String(meta.rows) })
  if (meta.rows_in_window != null) {
    rows.push({ label: '窗口内行数', value: String(meta.rows_in_window) })
  }
  if (meta.warmup_required_days != null) {
    rows.push({ label: '预热天数', value: `${meta.warmup_required_days} 天` })
  }
  rows.push({ label: '数据帧摘要', value: short(meta.frame_digest) })
  // C 复核口径：该哈希语义是「C 输入快照」的 sha256，不是结果哈希
  rows.push({
    label: 'C 输入快照哈希',
    value: short(meta.c_data_hash),
  })
  return rows
})

function goBack() {
  router.back()
}
</script>

<template>
  <main class="bt-detail">
    <header class="page-header">
      <div class="header-left">
        <h1 class="page-title">回测 #{{ backtestId }}</h1>
        <template v-if="detail">
          <span
            class="tag"
            :class="detail.semantics_version === 'v2_windowed' ? 'tag-v2' : 'tag-v1'"
          >
            {{ detail.semantics_version === 'v2_windowed' ? '参数化' : 'V1 快速' }}
          </span>
          <router-link class="stock-link" :to="`/stock/${detail.stock_code}`">
            {{ detail.stock_code }}
          </router-link>
        </template>
      </div>
      <router-link
        v-if="detail"
        class="back-link"
        :to="`/stock/${detail.stock_code}/backtests`"
      >
        该股票全部回测 →
      </router-link>
    </header>

    <!-- 加载态 -->
    <el-card v-if="loading" shadow="never" class="panel">
      <el-skeleton :rows="6" animated />
    </el-card>

    <!-- 404 -->
    <el-card v-else-if="notFound" shadow="never" class="panel">
      <el-result icon="warning" title="该回测记录不存在" sub-title="可能已被删除，或链接有误">
        <template #extra>
          <el-button type="primary" @click="goBack">返回</el-button>
        </template>
      </el-result>
    </el-card>

    <!-- 失败态 -->
    <el-card v-else-if="failed" shadow="never" class="panel">
      <el-result icon="error" title="加载失败" sub-title="回测详情获取失败，请稍后重试">
        <template #extra>
          <el-button type="primary" @click="load">重试</el-button>
        </template>
      </el-result>
    </el-card>

    <template v-else-if="detail">
      <!-- 历史横幅 -->
      <div class="history-banner">
        历史回测 · 创建于 {{ formatDateTime(detail.created_at) }} · 区间
        {{ detail.start_date }} ~ {{ detail.end_date }}
        <template v-if="detail.warmup_start_date">
          （预热自 {{ detail.warmup_start_date }}）
        </template>
      </div>

      <!-- 指标网格（快照缺失时摘要指标仍可展示） -->
      <el-card shadow="never" class="panel">
        <div class="metrics">
          <div v-for="metric in METRICS" :key="metric.key" class="metric">
            <span class="metric-label">{{ metric.label }}</span>
            <span :class="['metric-value', metricClass(detail[metric.key])]">
              {{ formatMetric(metric.kind, detail[metric.key]) }}
            </span>
          </div>
        </div>
      </el-card>

      <!-- 快照缺失 -->
      <el-card v-if="isMissing" shadow="never" class="panel">
        <el-result icon="info" title="历史快照缺失">
          <template #sub-title>
            {{ detail.snapshot_missing_reason || '该记录仅保存了摘要指标，无法回放曲线与成交明细' }}
          </template>
        </el-result>
      </el-card>

      <template v-else>
        <!-- 生效参数 -->
        <el-card v-if="paramRows.length > 0" shadow="never" class="panel">
          <template #header><span class="card-title">生效参数</span></template>
          <div class="param-grid">
            <div v-for="row in paramRows" :key="row.label" class="param">
              <span class="param-label">{{ row.label }}</span>
              <span class="param-value">{{ row.value }}</span>
            </div>
          </div>
        </el-card>

        <!-- 收益曲线（含基准） -->
        <el-card v-if="detail.equity_curve?.length" shadow="never" class="panel">
          <template #header><span class="card-title">收益曲线</span></template>
          <div class="chart-wrap">
            <ReturnCurveChart
              :equity-curve="detail.equity_curve"
              :benchmark-curve="detail.benchmark_curve"
              :initial-cash="detail.initial_cash"
            />
          </div>
        </el-card>

        <!-- 成交记录：内部滚动，不撑开页面 -->
        <el-card shadow="never" class="panel">
          <template #header>
            <div class="card-header">
              <span class="card-title">成交记录</span>
              <span class="card-sub">共 {{ detail.order_count }} 笔</span>
            </div>
          </template>
          <div v-if="hasTrades" class="trades-scroll">
            <table class="trades-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>信号日</th>
                  <th>执行日</th>
                  <th>方向</th>
                  <th>价格</th>
                  <th>股数</th>
                  <th>费用</th>
                  <th>往返盈亏</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="trade in detail.trades" :key="trade.order_id">
                  <td>{{ trade.order_id }}</td>
                  <td>{{ trade.signal_date }}</td>
                  <td>{{ trade.execution_date }}</td>
                  <td :class="trade.side === 'buy' ? 'up' : 'down'">
                    {{ trade.side === 'buy' ? '买入' : '卖出' }}
                  </td>
                  <td>{{ trade.execution_price.toFixed(2) }}</td>
                  <td>{{ trade.shares }}</td>
                  <td>{{ trade.fee.toFixed(2) }}</td>
                  <td :class="metricClass(trade.round_trip_pnl)">
                    {{ formatPnl(trade.round_trip_pnl) }}
                    <span class="pnl-pct">({{ formatPnlPct(trade.round_trip_return) }})</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-else class="no-trades">该区间无成交</p>
        </el-card>

        <!-- 数据元信息 -->
        <el-card v-if="metaRows.length > 0" shadow="never" class="panel">
          <template #header><span class="card-title">数据与校验</span></template>
          <div class="meta-grid">
            <div v-for="row in metaRows" :key="row.label" class="meta-row">
              <span class="meta-label">{{ row.label }}</span>
              <span class="meta-value">{{ row.value }}</span>
            </div>
          </div>
        </el-card>
      </template>
    </template>
  </main>
</template>

<style scoped>
.bt-detail {
  width: 100%;
  max-width: 880px;
  margin: 0 auto;
  box-sizing: border-box;
  padding: 16px 24px 48px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.page-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--border);
}

.header-left {
  display: flex;
  align-items: baseline;
  gap: 12px;
  min-width: 0;
}

.back-link {
  color: var(--text-faint);
  font-size: 12px;
  text-decoration: none;
  white-space: nowrap;
  cursor: pointer;
  transition: color 0.15s ease;
}

.back-link:hover {
  color: var(--accent);
}

.page-title {
  margin: 0;
  font-size: 18px;
  font-weight: 700;
  color: var(--text-main);
}

.stock-link {
  font-size: 12px;
  color: var(--text-faint);
  text-decoration: none;
  font-variant-numeric: tabular-nums;
}

.stock-link:hover {
  color: var(--accent);
}

.tag {
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 10px;
  letter-spacing: 0.04em;
}

.tag-v2 {
  border: 1px solid var(--accent);
  background: var(--accent-bg);
  color: var(--accent);
}

.tag-v1 {
  border: 1px solid var(--border-strong);
  color: var(--text-faint);
}

.history-banner {
  padding: 10px 14px;
  border: 1px solid var(--accent);
  border-radius: 8px;
  background: var(--accent-bg);
  color: var(--accent);
  font-size: 12px;
  letter-spacing: 0.02em;
}

.panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
}

.card-title {
  font-weight: 600;
  font-size: 13px;
}

.card-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
}

.card-sub {
  font-size: 11px;
  color: var(--text-faint);
}

.metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px 8px;
}

.metric {
  display: grid;
  gap: 2px;
}

.metric-label {
  color: var(--text-faint);
  font-size: 12px;
}

.metric-value {
  font-size: 16px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.metric-value.up,
.up {
  color: var(--up);
}

.metric-value.down,
.down {
  color: var(--down);
}

.param-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 12px 8px;
}

.param {
  display: grid;
  gap: 2px;
}

.param-label {
  color: var(--text-faint);
  font-size: 12px;
}

.param-value {
  font-size: 14px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.chart-wrap {
  height: 240px;
}

.trades-scroll {
  max-height: 280px;
  overflow-y: auto;
}

.trades-scroll::-webkit-scrollbar {
  width: 6px;
}

.trades-scroll::-webkit-scrollbar-thumb {
  background: var(--border-strong);
  border-radius: 3px;
}

.trades-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.trades-table th {
  position: sticky;
  top: 0;
  background: var(--surface);
  color: var(--text-faint);
  font-weight: 400;
  text-align: left;
  padding: 6px 8px;
  border-bottom: 1px solid var(--border);
}

.trades-table td {
  padding: 7px 8px;
  border-bottom: 1px solid var(--border);
  color: var(--text-sub);
}

.pnl-pct {
  font-size: 11px;
  opacity: 0.7;
}

.no-trades {
  margin: 0;
  padding: 12px 0;
  text-align: center;
  color: var(--text-faint);
  font-size: 12px;
}

.meta-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px 16px;
}

.meta-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  font-size: 12px;
}

.meta-label {
  color: var(--text-faint);
}

.meta-value {
  color: var(--text-sub);
  font-variant-numeric: tabular-nums;
}

@media (max-width: 760px) {
  .bt-detail {
    padding: 12px 12px 32px;
  }

  .metrics,
  .param-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .meta-grid {
    grid-template-columns: 1fr;
  }
}
</style>
