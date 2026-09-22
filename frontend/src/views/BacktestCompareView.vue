<script setup lang="ts">
// V3 F3：两个历史回测对照（/backtests/compare?a=<id>&b=<id>，A2）
// 只读回放：每个 ID 一次详情 GET；不重算、不请求行情/新闻/LLM。
// 独立状态：链接无效 / 同一记录 / 跨股票 / 记录不存在 / 单侧失败；
// epoch 防护：切换 URL 后旧请求不得覆盖新选择。
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { AxiosError } from 'axios'

import { fetchBacktestDetail } from '../api/backtests'
import type { BacktestDetail } from '../types/api'
import ReturnCurveChart from '../components/stock/ReturnCurveChart.vue'
import { formatDateTime } from '../utils/format'

const route = useRoute()
const router = useRouter()

// 解析 query 参数：须为正整数
function parseId(raw: unknown): number | null {
  const n = Number(raw)
  return Number.isInteger(n) && n > 0 ? n : null
}

const idA = computed(() => parseId(route.query.a))
const idB = computed(() => parseId(route.query.b))

const invalidQuery = computed(() => idA.value == null || idB.value == null)
const sameId = computed(() => !invalidQuery.value && idA.value === idB.value)

const detailA = ref<BacktestDetail | null>(null)
const detailB = ref<BacktestDetail | null>(null)
const loading = ref(true)
/** 404 的回测 ID（记录不存在） */
const notFoundIds = ref<number[]>([])
/** 非加载失败侧的回测 ID */
const failedIds = ref<number[]>([])
const crossStock = ref(false)

// 过期请求防护（同详情页 epoch 模式）：慢响应后切换 URL，旧响应直接丢弃
const epoch = ref(0)

type SideResult = { ok: true; data: BacktestDetail } | { ok: false; notFound: boolean }

async function loadSide(id: number): Promise<SideResult> {
  try {
    const res = await fetchBacktestDetail(id)
    return { ok: true, data: res.data }
  } catch (error) {
    // 契约：未知 ID 返回 HTTP 404 + code=40005
    return { ok: false, notFound: error instanceof AxiosError && error.response?.status === 404 }
  }
}

async function load() {
  const currentEpoch = ++epoch.value
  detailA.value = null
  detailB.value = null
  notFoundIds.value = []
  failedIds.value = []
  crossStock.value = false
  if (invalidQuery.value || sameId.value) {
    loading.value = false
    return
  }
  loading.value = true
  // 每个 ID 各一次详情 GET；刷新重新读取允许
  const [ra, rb] = await Promise.all([loadSide(idA.value!), loadSide(idB.value!)])
  if (epoch.value !== currentEpoch) return
  const notFound: number[] = []
  const failed: number[] = []
  const details: BacktestDetail[] = []
  for (const [result, id] of [
    [ra, idA.value],
    [rb, idB.value],
  ] as const) {
    if (result.ok) details.push(result.data)
    else if (result.notFound) notFound.push(id!)
    else failed.push(id!)
  }
  notFoundIds.value = notFound
  failedIds.value = failed
  if (details.length === 2) {
    detailA.value = details[0]
    detailB.value = details[1]
    crossStock.value = details[0].stock_code !== details[1].stock_code
  }
  loading.value = false
}

watch(() => route.query, load, { immediate: true })

const ready = computed(
  () =>
    detailA.value != null &&
    detailB.value != null &&
    !crossStock.value &&
    notFoundIds.value.length === 0 &&
    failedIds.value.length === 0,
)

// 不同区间/资金/语义/精度的口径提示（可见提示，不裁剪窗口）
const caveats = computed(() => {
  const a = detailA.value
  const b = detailB.value
  if (!a || !b) return []
  const out: string[] = []
  if (a.start_date !== b.start_date || a.end_date !== b.end_date) out.push('两条记录回测区间不同')
  if (a.initial_cash !== b.initial_cash) out.push('初始资金不同')
  if (a.semantics_version !== b.semantics_version) out.push('执行语义不同（v1/v2）')
  if (a.c_result_exact === false || b.c_result_exact === false) {
    out.push('含旧精度结果（c_result_exact=false），指标精度可能不同')
  }
  if (a.snapshot_status === 'missing' || b.snapshot_status === 'missing') {
    out.push('含快照缺失的旧记录，仅能对照摘要指标')
  }
  return out
})

// ---- 基本信息对照（每行 A | B 两列）----
function semanticsLabel(d: BacktestDetail): string {
  return d.semantics_version === 'v2_windowed' ? '参数化（v2_windowed）' : 'V1 快速（v1_legacy）'
}

function shortHash(hash?: string | null): string {
  if (!hash) return '—'
  return `${hash.slice(0, 8)}…${hash.slice(-8)}`
}

const infoRows = computed(() => {
  const a = detailA.value
  const b = detailB.value
  if (!a || !b) return []
  const rows: Array<{ label: string; a: string; b: string; diff?: boolean }> = [
    { label: '回测 ID', a: `#${a.backtest_id}`, b: `#${b.backtest_id}` },
    { label: '股票', a: a.stock_code, b: b.stock_code, diff: a.stock_code !== b.stock_code },
    { label: '策略', a: a.strategy_name, b: b.strategy_name, diff: a.strategy_name !== b.strategy_name },
    {
      label: '执行语义',
      a: semanticsLabel(a),
      b: semanticsLabel(b),
      diff: a.semantics_version !== b.semantics_version,
    },
    {
      label: '算法版本',
      a: a.c_algorithm_version ?? '—',
      b: b.c_algorithm_version ?? '—',
      diff: a.c_algorithm_version !== b.c_algorithm_version,
    },
    {
      label: '请求区间',
      a: `${a.start_date} ~ ${a.end_date}`,
      b: `${b.start_date} ~ ${b.end_date}`,
      diff: a.start_date !== b.start_date || a.end_date !== b.end_date,
    },
    {
      label: '实际区间',
      a: a.data_meta?.actual_start_date
        ? `${a.data_meta.actual_start_date} ~ ${a.data_meta.actual_end_date ?? '—'}`
        : '—',
      b: b.data_meta?.actual_start_date
        ? `${b.data_meta.actual_start_date} ~ ${b.data_meta.actual_end_date ?? '—'}`
        : '—',
    },
    {
      label: '预热起点',
      a: a.warmup_start_date ?? '—',
      b: b.warmup_start_date ?? '—',
      diff: a.warmup_start_date !== b.warmup_start_date,
    },
    {
      label: 'C 输入快照哈希',
      a: shortHash(a.c_data_hash),
      b: shortHash(b.c_data_hash),
    },
    {
      label: '创建时间',
      a: formatDateTime(a.created_at),
      b: formatDateTime(b.created_at),
    },
  ]
  return rows
})

// ---- 参数对照（MA/MACD 字段通用，白名单并集；差异高亮）----
const PARAM_META: Array<{ key: string; label: string; kind: 'period' | 'cash' | 'percent' }> = [
  { key: 'ma_short_period', label: '短均线（日）', kind: 'period' },
  { key: 'ma_long_period', label: '长均线（日）', kind: 'period' },
  { key: 'macd_fast_period', label: 'MACD 快线周期', kind: 'period' },
  { key: 'macd_slow_period', label: 'MACD 慢线周期', kind: 'period' },
  { key: 'macd_signal_period', label: 'MACD 信号线周期', kind: 'period' },
  { key: 'initial_cash', label: '初始资金（元）', kind: 'cash' },
  { key: 'transaction_cost', label: '交易成本', kind: 'percent' },
  { key: 'slippage', label: '滑点', kind: 'percent' },
]

function formatParamValue(
  kind: 'period' | 'cash' | 'percent',
  value: number | undefined,
): string {
  if (value == null) return '—'
  if (kind === 'cash') return value.toLocaleString()
  if (kind === 'percent') return `${(value * 100).toFixed(3)}%`
  return String(value)
}

const paramRows = computed(() => {
  const a = detailA.value?.effective_parameters as Record<string, number> | null | undefined
  const b = detailB.value?.effective_parameters as Record<string, number> | null | undefined
  return PARAM_META.filter((meta) => a?.[meta.key] != null || b?.[meta.key] != null).map(
    (meta) => ({
      label: meta.label,
      a: formatParamValue(meta.kind, a?.[meta.key]),
      b: formatParamValue(meta.kind, b?.[meta.key]),
      diff: a?.[meta.key] !== b?.[meta.key],
    }),
  )
})

const paramsMissing = computed(() => paramRows.value.length === 0)

// ---- 指标对照（保留单位与 null，不做优胜判断）----
function formatMetric(kind: 'percent' | 'decimal' | 'integer', value: number | null): string {
  if (value == null) return '—'
  if (kind === 'percent') {
    const sign = value > 0 ? '+' : ''
    return `${sign}${(value * 100).toFixed(2)}%`
  }
  if (kind === 'decimal') return value.toFixed(2)
  return String(value)
}

const METRICS = [
  { key: 'total_return', label: '总收益', kind: 'percent' },
  { key: 'annual_return', label: '年化收益', kind: 'percent' },
  { key: 'max_drawdown', label: '最大回撤', kind: 'percent' },
  { key: 'sharpe_ratio', label: '夏普率', kind: 'decimal' },
  { key: 'win_rate', label: '胜率', kind: 'percent' },
  { key: 'trade_count', label: '往返次数', kind: 'integer' },
] as const

const metricRows = computed(() => {
  const a = detailA.value
  const b = detailB.value
  if (!a || !b) return []
  return METRICS.map((metric) => ({
    label: metric.label,
    a: formatMetric(metric.kind, a[metric.key]),
    b: formatMetric(metric.kind, b[metric.key]),
  }))
})

// ---- 并排曲线：只做既有 equity / initial_cash - 1 换算；资金无效不画虚假 0 曲线 ----
function curveState(d: BacktestDetail): 'ok' | 'missing' | 'invalid-cash' {
  if (!d.equity_curve || d.equity_curve.length === 0) return 'missing'
  if (!Number.isFinite(d.initial_cash) || d.initial_cash <= 0) return 'invalid-cash'
  return 'ok'
}

function goBack() {
  router.back()
}
</script>

<template>
  <main class="compare-page">
    <header class="page-header">
      <div class="header-left">
        <a class="back-link" @click="goBack">← 返回</a>
        <h1 class="page-title">回测对照</h1>
        <template v-if="ready">
          <span class="stock-chip">{{ detailA!.stock_code }}</span>
          <span class="ids-chip">#{{ idA }} vs #{{ idB }}</span>
        </template>
      </div>
    </header>

    <!-- 链接无效：a/b 须为正整数 -->
    <el-card v-if="invalidQuery" shadow="never" class="panel">
      <el-result icon="warning" title="链接无效" sub-title="a、b 参数须为正整数的回测 ID">
        <template #extra>
          <el-button type="primary" @click="goBack">返回</el-button>
        </template>
      </el-result>
    </el-card>

    <!-- 同一份记录 -->
    <el-card v-else-if="sameId" shadow="never" class="panel">
      <el-result icon="warning" title="不能对照同一份记录" sub-title="请选择两个不同的回测 ID">
        <template #extra>
          <el-button type="primary" @click="goBack">返回</el-button>
        </template>
      </el-result>
    </el-card>

    <!-- 加载 -->
    <el-card v-else-if="loading" shadow="never" class="panel">
      <el-skeleton :rows="6" animated />
    </el-card>

    <template v-else>
      <!-- 记录不存在（404） -->
      <el-card v-if="notFoundIds.length > 0" shadow="never" class="panel">
        <el-result
          icon="warning"
          :title="`回测 #${notFoundIds.join('、#')} 不存在`"
          sub-title="可能已被删除，或链接有误"
        >
          <template #extra>
            <el-button type="primary" @click="goBack">返回</el-button>
          </template>
        </el-result>
      </el-card>

      <!-- 单侧加载失败（可重试） -->
      <el-card v-if="failedIds.length > 0" shadow="never" class="panel">
        <el-result
          icon="error"
          :title="`回测 #${failedIds.join('、#')} 详情获取失败`"
          sub-title="请稍后重试"
        >
          <template #extra>
            <el-button type="primary" @click="load">重试</el-button>
          </template>
        </el-result>
      </el-card>

      <!-- 跨股票 -->
      <el-card v-else-if="crossStock" shadow="never" class="panel">
        <el-result
          icon="warning"
          title="不能对照不同股票的回测"
          :sub-title="`${detailA?.stock_code} 与 ${detailB?.stock_code} 不是同一只股票`"
        >
          <template #extra>
            <el-button type="primary" @click="goBack">返回</el-button>
          </template>
        </el-result>
      </el-card>

      <!-- 正常对照 -->
      <template v-else-if="ready">
        <!-- 口径提示：不裁剪窗口、不插值，只做可见提示 -->
        <div v-if="caveats.length > 0" class="caveat-banner">
          <span v-for="text in caveats" :key="text" class="caveat-item">{{ text }}</span>
        </div>

        <!-- 基本信息 -->
        <el-card shadow="never" class="panel">
          <template #header><span class="card-title">基本信息</span></template>
          <table class="cmp-table">
            <thead>
              <tr>
                <th class="col-label"></th>
                <th>A · #{{ detailA!.backtest_id }}</th>
                <th>B · #{{ detailB!.backtest_id }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in infoRows" :key="row.label">
                <td class="col-label">{{ row.label }}</td>
                <td :class="{ diff: row.diff }">{{ row.a }}</td>
                <td :class="{ diff: row.diff }">{{ row.b }}</td>
              </tr>
            </tbody>
          </table>
        </el-card>

        <!-- 参数差异 -->
        <el-card shadow="never" class="panel">
          <template #header><span class="card-title">参数对照</span></template>
          <table v-if="!paramsMissing" class="cmp-table">
            <thead>
              <tr>
                <th class="col-label"></th>
                <th>A · #{{ detailA!.backtest_id }}</th>
                <th>B · #{{ detailB!.backtest_id }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in paramRows" :key="row.label">
                <td class="col-label">{{ row.label }}</td>
                <td :class="{ diff: row.diff }">{{ row.a }}</td>
                <td :class="{ diff: row.diff }">{{ row.b }}</td>
              </tr>
            </tbody>
          </table>
          <p v-else class="missing-note">两条记录均未保存参数快照，无法对照参数</p>
        </el-card>

        <!-- 指标对照（保留 null 为「—」，不做优胜判断） -->
        <el-card shadow="never" class="panel">
          <template #header><span class="card-title">指标对照</span></template>
          <table class="cmp-table">
            <thead>
              <tr>
                <th class="col-label"></th>
                <th>A · #{{ detailA!.backtest_id }}</th>
                <th>B · #{{ detailB!.backtest_id }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in metricRows" :key="row.label">
                <td class="col-label">{{ row.label }}</td>
                <td>{{ row.a }}</td>
                <td>{{ row.b }}</td>
              </tr>
            </tbody>
          </table>
        </el-card>

        <!-- 并排权益曲线：一份结果一张图，不叠加、不对齐窗口 -->
        <div class="curves-grid">
          <el-card shadow="never" class="panel">
            <template #header>
              <div class="card-header">
                <span class="card-title">A · #{{ detailA!.backtest_id }} 权益曲线</span>
                <span class="card-sub">
                  {{ detailA!.start_date }} ~ {{ detailA!.end_date }} · 资金
                  {{ detailA!.initial_cash.toLocaleString() }}
                </span>
              </div>
            </template>
            <div v-if="curveState(detailA!) === 'ok'" class="chart-wrap">
              <ReturnCurveChart
                :equity-curve="detailA!.equity_curve!"
                :benchmark-curve="detailA!.benchmark_curve"
                :initial-cash="detailA!.initial_cash"
              />
            </div>
            <p v-else-if="curveState(detailA!) === 'invalid-cash'" class="missing-note">
              初始资金无效，无法换算收益率（不绘制虚假 0 曲线）
            </p>
            <p v-else class="missing-note">该记录缺少权益曲线，无法展示</p>
          </el-card>

          <el-card shadow="never" class="panel">
            <template #header>
              <div class="card-header">
                <span class="card-title">B · #{{ detailB!.backtest_id }} 权益曲线</span>
                <span class="card-sub">
                  {{ detailB!.start_date }} ~ {{ detailB!.end_date }} · 资金
                  {{ detailB!.initial_cash.toLocaleString() }}
                </span>
              </div>
            </template>
            <div v-if="curveState(detailB!) === 'ok'" class="chart-wrap">
              <ReturnCurveChart
                :equity-curve="detailB!.equity_curve!"
                :benchmark-curve="detailB!.benchmark_curve"
                :initial-cash="detailB!.initial_cash"
              />
            </div>
            <p v-else-if="curveState(detailB!) === 'invalid-cash'" class="missing-note">
              初始资金无效，无法换算收益率（不绘制虚假 0 曲线）
            </p>
            <p v-else class="missing-note">该记录缺少权益曲线，无法展示</p>
          </el-card>
        </div>
      </template>
    </template>
  </main>
</template>

<style scoped>
.compare-page {
  width: 100%;
  max-width: 1080px;
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

.stock-chip,
.ids-chip {
  font-size: 12px;
  color: var(--text-faint);
  font-variant-numeric: tabular-nums;
}

.ids-chip {
  padding: 1px 8px;
  border: 1px solid var(--accent);
  border-radius: 999px;
  color: var(--accent);
  font-size: 10px;
  letter-spacing: 0.04em;
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
  gap: 8px;
}

.card-sub {
  font-size: 11px;
  color: var(--text-faint);
  font-variant-numeric: tabular-nums;
}

.caveat-banner {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 10px 14px;
  border: 1px solid rgba(230, 180, 80, 0.4);
  border-radius: 8px;
  background: rgba(230, 180, 80, 0.06);
}

.caveat-item {
  color: rgba(230, 180, 80, 0.95);
  font-size: 12px;
}

.caveat-item + .caveat-item::before {
  content: '·';
  margin-right: 6px;
  opacity: 0.6;
}

/* 对照表：标签列窄，A/B 两列等宽 */
.cmp-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.cmp-table th {
  color: var(--text-faint);
  font-weight: 600;
  text-align: left;
  padding: 6px 10px;
  border-bottom: 1px solid var(--border);
  font-variant-numeric: tabular-nums;
}

.cmp-table td {
  padding: 7px 10px;
  border-bottom: 1px solid var(--border);
  color: var(--text-sub);
  font-variant-numeric: tabular-nums;
}

.cmp-table tbody tr:last-child td {
  border-bottom: none;
}

.col-label {
  width: 22%;
  color: var(--text-faint);
  white-space: nowrap;
}

.cmp-table td.diff {
  color: var(--accent);
  font-weight: 600;
}

.missing-note {
  margin: 0;
  padding: 12px 0;
  text-align: center;
  color: var(--text-faint);
  font-size: 12px;
}

.curves-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.chart-wrap {
  height: 260px;
}

@media (max-width: 880px) {
  .curves-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 760px) {
  .compare-page {
    padding: 12px 12px 32px;
  }

  .col-label {
    width: 30%;
  }
}
</style>
