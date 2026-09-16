<script setup lang="ts">
// A2：策略回测面板（工作台内，自包含数据逻辑）
// 进入页面自动跑一次 v1_legacy 快速回测（省略 parameters）；
// 展开「自定义参数」可提交 v2_windowed 参数化回测（C 定稿：显式传 parameters，
// 白名单五字段，页面显示百分数、发送小数；50004 表示 V2 引擎未就绪，不产生记录）
import { ref, watch } from 'vue'
import { AxiosError } from 'axios'

import { runBacktest } from '../../api/stocks'
import type { BacktestData, BacktestParameters } from '../../types/api'
import {
  BACKTEST_PARAM_DEFAULTS,
  BACKTEST_PARAM_LIMITS,
  toBacktestParameters,
  validateBacktestForm,
  type BacktestFormValues,
} from '../../utils/backtestParams'
import ReturnCurveChart from './ReturnCurveChart.vue'

const props = defineProps<{ stockCode: string }>()

const result = ref<BacktestData | null>(null)
const loading = ref(true) // 初次加载 / 切股重载
const failed = ref(false)
const submitting = ref(false) // 参数化提交中（保留旧结果展示）
const submitError = ref('')

// 过期请求防护（同 StockDetailView 的 epoch 模式）
const epoch = ref(0)

// ---- 参数表单（成本/滑点页面显示百分数，提交时 /100 转小数）----
const formOpen = ref(false)
const dateRange = ref<[string, string] | null>(null)
const initialCash = ref<number | null>(BACKTEST_PARAM_DEFAULTS.initial_cash)
const shortWindow = ref<number | null>(BACKTEST_PARAM_DEFAULTS.ma_short_period)
const longWindow = ref<number | null>(BACKTEST_PARAM_DEFAULTS.ma_long_period)
const transactionCostPct = ref<number | null>(BACKTEST_PARAM_DEFAULTS.transaction_cost * 100)
const slippagePct = ref<number | null>(BACKTEST_PARAM_DEFAULTS.slippage * 100)
const formErrors = ref<string[]>([])

// 表单被修改但未重新运行时，提示当前展示的是旧参数结果
const dirty = ref(false)
watch([dateRange, initialCash, shortWindow, longWindow, transactionCostPct, slippagePct], () => {
  dirty.value = true
})

// 最近一次参数化运行的参数（用于结果标注）
const lastRunParams = ref<BacktestParameters | null>(null)
const lastRunRange = ref<[string, string] | null>(null)

const METRICS = [
  { key: 'total_return', label: '总收益', kind: 'percent' },
  { key: 'annual_return', label: '年化收益', kind: 'percent' },
  { key: 'max_drawdown', label: '最大回撤', kind: 'percent' },
  { key: 'sharpe_ratio', label: '夏普率', kind: 'decimal' },
  { key: 'win_rate', label: '胜率', kind: 'percent' },
  { key: 'trade_count', label: '往返次数', kind: 'integer' },
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

function metricClass(value: number | null | undefined): string {
  if (value == null) return ''
  if (value > 0) return 'up'
  if (value < 0) return 'down'
  return ''
}

function formatPnl(value: number | null): string {
  if (value == null) return '—'
  const sign = value > 0 ? '+' : ''
  return `${sign}${value.toFixed(2)}`
}

function formatPct(value: number): string {
  return `${(value * 100).toFixed(3)}%`
}

// 初次加载 / 切股重载：v1_legacy 快速回测（完全省略 parameters）
// 状态交接约定（C 复核）：
// - 每次新请求（load/submit）接管全部进行态，旧请求的响应由 epoch 丢弃
// - load 负责清 submitting（切股时旧提交可能还在途，其 finally 因 epoch 守卫不会自清）
// - submit 负责清 loading/failed（V1 在途或失败时，以 V2 提交为新基准）
async function load() {
  const currentEpoch = ++epoch.value
  loading.value = true
  failed.value = false
  submitting.value = false
  result.value = null
  submitError.value = ''
  dirty.value = false
  lastRunParams.value = null
  lastRunRange.value = null
  try {
    const res = await runBacktest({ stock_code: props.stockCode })
    if (epoch.value !== currentEpoch) return
    result.value = res.data
  } catch {
    if (epoch.value !== currentEpoch) return
    failed.value = true
  } finally {
    if (epoch.value === currentEpoch) loading.value = false
  }
}

watch(() => props.stockCode, load, { immediate: true })

// 提交参数化回测（v2_windowed）
async function submit() {
  const values: BacktestFormValues = {
    start_date: dateRange.value?.[0] ?? '',
    end_date: dateRange.value?.[1] ?? '',
    initial_cash: initialCash.value,
    short_window: shortWindow.value,
    long_window: longWindow.value,
    transaction_cost:
      transactionCostPct.value == null ? null : transactionCostPct.value / 100,
    slippage: slippagePct.value == null ? null : slippagePct.value / 100,
  }
  const errors = validateBacktestForm(values)
  formErrors.value = errors
  if (errors.length > 0) return

  const currentEpoch = ++epoch.value
  submitting.value = true
  submitError.value = ''
  // V2 提交取代 V1 的在途/失败状态（V1 响应会被 epoch 守卫丢弃）
  loading.value = false
  failed.value = false
  try {
    const res = await runBacktest({
      stock_code: props.stockCode,
      start_date: values.start_date,
      end_date: values.end_date,
      parameters: toBacktestParameters(values),
    })
    if (epoch.value !== currentEpoch) return
    result.value = res.data
    lastRunParams.value = toBacktestParameters(values)
    lastRunRange.value = [values.start_date, values.end_date]
    dirty.value = false
  } catch (error) {
    if (epoch.value !== currentEpoch) return
    // 拦截器对业务码会以 Error(中文文案) reject；HTTP 错误文案已由拦截器弹出
    submitError.value =
      !(error instanceof AxiosError) && error instanceof Error && error.message
        ? error.message
        : '回测失败，请稍后重试'
  } finally {
    if (epoch.value === currentEpoch) submitting.value = false
  }
}

function resetForm() {
  dateRange.value = null
  initialCash.value = BACKTEST_PARAM_DEFAULTS.initial_cash
  shortWindow.value = BACKTEST_PARAM_DEFAULTS.ma_short_period
  longWindow.value = BACKTEST_PARAM_DEFAULTS.ma_long_period
  transactionCostPct.value = BACKTEST_PARAM_DEFAULTS.transaction_cost * 100
  slippagePct.value = BACKTEST_PARAM_DEFAULTS.slippage * 100
  formErrors.value = []
}
</script>

<template>
  <el-card shadow="never" class="card-lift">
    <template #header>
      <div class="header">
        <div class="header-left">
          <span>策略回测</span>
          <span
            v-if="result"
            class="tag"
            :class="result.semantics_version === 'v2_windowed' ? 'tag-v2' : 'tag-v1'"
          >
            {{ result.semantics_version === 'v2_windowed' ? '参数化' : 'V1 快速' }}
          </span>
        </div>
        <div class="header-right">
          <router-link class="history-link" :to="`/stock/${stockCode}/backtests`">
            历史回测 →
          </router-link>
          <button class="toggle" type="button" @click="formOpen = !formOpen">
            {{ formOpen ? '收起参数 ▴' : '自定义参数 ▾' }}
          </button>
        </div>
      </div>
    </template>

    <!-- 参数表单 -->
    <div v-if="formOpen" class="form">
      <div class="field field-full">
        <label class="field-label">回测区间（最长 {{ BACKTEST_PARAM_LIMITS.maxRangeYears }} 个日历年）</label>
        <el-date-picker
          v-model="dateRange"
          type="daterange"
          value-format="YYYY-MM-DD"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          unlink-panels
          class="date-picker"
        />
      </div>
      <div class="form-grid">
        <div class="field">
          <label class="field-label">短均线（日）</label>
          <el-input-number
            v-model="shortWindow"
            :min="BACKTEST_PARAM_LIMITS.shortWindowMin"
            :max="BACKTEST_PARAM_LIMITS.longWindowMax"
            :precision="0"
            :controls="false"
            class="num-input"
          />
        </div>
        <div class="field">
          <label class="field-label">长均线（日）</label>
          <el-input-number
            v-model="longWindow"
            :min="BACKTEST_PARAM_LIMITS.shortWindowMin"
            :max="BACKTEST_PARAM_LIMITS.longWindowMax"
            :precision="0"
            :controls="false"
            class="num-input"
          />
        </div>
        <div class="field">
          <label class="field-label">初始资金（元）</label>
          <el-input-number
            v-model="initialCash"
            :min="1"
            :step="10000"
            :controls="false"
            class="num-input"
          />
        </div>
        <div class="field">
          <label class="field-label">交易成本（%）</label>
          <el-input-number
            v-model="transactionCostPct"
            :min="0"
            :max="99"
            :step="0.1"
            :precision="3"
            :controls="false"
            class="num-input"
          />
        </div>
        <div class="field">
          <label class="field-label">滑点（%）</label>
          <el-input-number
            v-model="slippagePct"
            :min="0"
            :max="99"
            :step="0.1"
            :precision="3"
            :controls="false"
            class="num-input"
          />
        </div>
      </div>

      <ul v-if="formErrors.length > 0" class="errors">
        <li v-for="error in formErrors" :key="error">{{ error }}</li>
      </ul>

      <div class="form-actions">
        <el-button type="primary" :loading="submitting" @click="submit">
          运行参数化回测
        </el-button>
        <el-button text @click="resetForm">恢复默认</el-button>
      </div>
    </div>

    <!-- 提交错误：无论有无旧结果都要可见（V1 在途时提交 V2 失败，result 仍为 null） -->
    <p v-if="submitError" class="submit-error">{{ submitError }}</p>

    <!-- 初次加载 -->
    <el-skeleton v-if="loading" :rows="4" animated />

    <!-- 初次加载失败 -->
    <div v-else-if="failed" class="failed">
      <p class="failed-text">回测加载失败</p>
      <el-button size="small" @click="load">重试</el-button>
    </div>

    <!-- 结果 -->
    <template v-else-if="result">
      <p v-if="dirty" class="stale-hint">参数已修改，以下为上次运行结果</p>
      <p v-if="lastRunParams && lastRunRange" class="params-line">
        {{ lastRunRange[0] }} ~ {{ lastRunRange[1] }} · MA
        {{ lastRunParams.ma_short_period }}/{{ lastRunParams.ma_long_period }} · 初始资金
        {{ lastRunParams.initial_cash.toLocaleString() }} · 成本
        {{ formatPct(lastRunParams.transaction_cost) }} · 滑点
        {{ formatPct(lastRunParams.slippage) }}
      </p>

      <div class="metrics">
        <div v-for="metric in METRICS" :key="metric.key" class="metric">
          <span class="metric-label">{{ metric.label }}</span>
          <span :class="['metric-value', metricClass(result[metric.key])]">
            {{ formatMetric(metric.kind, result[metric.key]) }}
          </span>
        </div>
        <div v-if="result.order_count != null" class="metric">
          <span class="metric-label">成交笔数</span>
          <span class="metric-value">{{ result.order_count }}</span>
        </div>
      </div>

      <div v-if="result.equity_curve.length > 0" class="curve">
        <ReturnCurveChart
          :equity-curve="result.equity_curve"
          :benchmark-curve="result.benchmark_curve"
          :initial-cash="result.initial_cash"
        />
      </div>

      <!-- 成交记录（v2）：内部滚动，不撑开卡片 -->
      <template v-if="result.trades">
        <div class="trades-title">成交记录（{{ result.order_count ?? result.trades.length }} 笔）</div>
        <div v-if="result.trades.length > 0" class="trades-scroll">
          <table class="trades-table">
            <thead>
              <tr>
                <th>执行日</th>
                <th>方向</th>
                <th>价格</th>
                <th>股数</th>
                <th>费用</th>
                <th>往返盈亏</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="trade in result.trades" :key="trade.order_id">
                <td>{{ trade.execution_date }}</td>
                <td :class="trade.side === 'buy' ? 'up' : 'down'">
                  {{ trade.side === 'buy' ? '买入' : '卖出' }}
                </td>
                <td>{{ trade.execution_price.toFixed(2) }}</td>
                <td>{{ trade.shares }}</td>
                <td>{{ trade.fee.toFixed(2) }}</td>
                <td :class="metricClass(trade.round_trip_pnl)">
                  {{ formatPnl(trade.round_trip_pnl) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else class="no-trades">该区间无成交</p>
      </template>
    </template>
  </el-card>
</template>

<style scoped>
.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-weight: 600;
}

.header-left,
.header-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.tag {
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 10px;
  font-weight: 400;
  letter-spacing: 0.04em;
}

.tag-v2 {
  border: 1px solid rgba(212, 169, 88, 0.4);
  background: rgba(212, 169, 88, 0.08);
  color: rgba(212, 169, 88, 0.9);
}

.tag-v1 {
  border: 1px solid var(--border-strong);
  color: var(--text-faint);
}

.history-link {
  color: var(--text-faint);
  font-size: 12px;
  font-weight: 400;
  text-decoration: none;
  white-space: nowrap;
  transition: color 0.15s ease;
}

.history-link:hover {
  color: var(--accent);
}

.toggle {
  padding: 0;
  border: none;
  background: none;
  color: var(--accent);
  font-size: 12px;
  cursor: pointer;
  white-space: nowrap;
}

.toggle:hover {
  text-decoration: underline;
}

/* ---- 参数表单 ---- */
.form {
  margin-bottom: 14px;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-hover);
}

.field {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.field-full {
  margin-bottom: 10px;
}

.field-label {
  color: var(--text-faint);
  font-size: 11px;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.date-picker,
.num-input {
  width: 100%;
}

.errors {
  margin: 10px 0 0;
  padding: 8px 12px 8px 28px;
  border: 1px solid rgba(255, 77, 79, 0.35);
  border-radius: 6px;
  background: rgba(255, 77, 79, 0.06);
  color: var(--up);
  font-size: 12px;
  line-height: 1.7;
}

.form-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
}

/* ---- 结果 ---- */
.stale-hint {
  margin: 0 0 8px;
  color: rgba(230, 180, 80, 0.9);
  font-size: 11px;
}

.params-line {
  margin: 0 0 10px;
  color: var(--text-faint);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

.submit-error {
  margin: 0 0 10px;
  color: var(--up);
  font-size: 12px;
}

.failed {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 24px 0;
}

.failed-text {
  margin: 0;
  color: var(--text-faint);
  font-size: 13px;
}

.metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px 8px;
  margin-bottom: 14px;
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

.curve {
  width: 100%;
  height: 200px;
}

/* ---- 成交记录 ---- */
.trades-title {
  margin: 14px 0 6px;
  color: var(--text-faint);
  font-size: 12px;
}

.trades-scroll {
  max-height: 200px;
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

.no-trades {
  margin: 0;
  padding: 12px 0;
  text-align: center;
  color: var(--text-faint);
  font-size: 12px;
}

@media (max-width: 760px) {
  .metrics,
  .form-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
