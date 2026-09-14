<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

import type { BacktestData } from '../../types/api'

echarts.use([LineChart, GridComponent, TooltipComponent, CanvasRenderer])

const props = defineProps<{ data: BacktestData }>()

const METRICS = [
  { key: 'total_return', label: '总收益', kind: 'percent' },
  { key: 'annual_return', label: '年化收益', kind: 'percent' },
  { key: 'max_drawdown', label: '最大回撤', kind: 'percent' },
  { key: 'sharpe_ratio', label: '夏普率', kind: 'decimal' },
  { key: 'win_rate', label: '胜率', kind: 'percent' },
  { key: 'trade_count', label: '交易次数', kind: 'integer' },
] as const

type MetricValue = number | null

function formatMetric(kind: 'percent' | 'decimal' | 'integer', value: MetricValue): string {
  if (value == null) return '—'
  if (kind === 'percent') {
    const sign = value > 0 ? '+' : ''
    return `${sign}${(value * 100).toFixed(2)}%`
  }
  if (kind === 'decimal') return value.toFixed(2)
  return String(value)
}

function metricClass(value: MetricValue): string {
  if (value == null) return ''
  if (value > 0) return 'up'
  if (value < 0) return 'down'
  return ''
}

const chartEl = ref<HTMLElement | null>(null)
let chart: echarts.ECharts | null = null

// equity 是绝对权益（initial_cash 起步），展示统一换算为累计收益率
const curve = computed(() => {
  const cash = props.data.initial_cash
  return props.data.equity_curve.map((point) => ({
    trade_date: point.trade_date,
    ret: cash ? point.equity / cash - 1 : 0,
  }))
})

function render() {
  if (!chart) return
  chart.setOption(
    {
      animation: false,
      tooltip: {
        trigger: 'axis',
        backgroundColor: '#14171d',
        borderColor: 'rgba(255,255,255,0.12)',
        borderWidth: 1,
        textStyle: { color: '#f2f2f2' },
        valueFormatter: (value: number) => `${(value * 100).toFixed(2)}%`,
      },
      grid: { left: 52, right: 12, top: 12, bottom: 24 },
      xAxis: {
        type: 'category',
        data: curve.value.map((point) => point.trade_date.slice(5)),
        axisLabel: { color: 'rgba(255,255,255,0.45)', fontSize: 11 },
        axisLine: { lineStyle: { color: 'rgba(255,255,255,0.12)' } },
        axisTick: { show: false },
      },
      yAxis: {
        type: 'value',
        scale: true,
        axisLabel: {
          color: 'rgba(255,255,255,0.45)',
          fontSize: 11,
          formatter: (value: number) => `${(value * 100).toFixed(0)}%`,
        },
        splitLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } },
      },
      series: [
        {
          name: '累计收益率曲线',
          type: 'line',
          data: curve.value.map((point) => point.ret),
          symbol: 'none',
          lineStyle: { width: 1.5, color: '#d4a958' },
          itemStyle: { color: '#d4a958' },
          areaStyle: {
            color: {
              type: 'linear',
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: 'rgba(212,169,88,0.16)' },
                { offset: 1, color: 'rgba(212,169,88,0)' },
              ],
            },
          },
        },
      ],
    },
    true,
  )
}

onMounted(() => {
  if (chartEl.value) {
    chart = echarts.init(chartEl.value)
    render()
  }
})

watch(curve, render)

onBeforeUnmount(() => {
  chart?.dispose()
  chart = null
})
</script>

<template>
  <el-card shadow="never" class="card-lift">
    <template #header>
      <div class="header">
        <span>策略回测</span>
        <span class="id">{{ data.stock_code }}</span>
      </div>
    </template>

    <div class="metrics">
      <div v-for="metric in METRICS" :key="metric.key" class="metric">
        <span class="metric-label">{{ metric.label }}</span>
        <span :class="['metric-value', metricClass(data[metric.key])]">
          {{ formatMetric(metric.kind, data[metric.key]) }}
        </span>
      </div>
    </div>

    <div v-if="curve.length > 0" ref="chartEl" class="curve" />
  </el-card>
</template>

<style scoped>
.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: 600;
}

.id {
  color: var(--text-faint);
  font-size: 12px;
  font-weight: 400;
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
}

.metric-value.up {
  color: #ff4d4f;
}

.metric-value.down {
  color: #00b386;
}

.curve {
  width: 100%;
  height: 160px;
}

@media (max-width: 760px) {
  .metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
