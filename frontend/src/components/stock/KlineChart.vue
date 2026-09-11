<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart, CandlestickChart, LineChart } from 'echarts/charts'
import {
  AxisPointerComponent,
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  TooltipComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

import type { IndicatorsItem, KlineItem } from '../../types/api'

echarts.use([
  CandlestickChart,
  BarChart,
  LineChart,
  GridComponent,
  TooltipComponent,
  AxisPointerComponent,
  DataZoomComponent,
  LegendComponent,
  CanvasRenderer,
])

const props = defineProps<{ items: KlineItem[]; indicators?: IndicatorsItem[] }>()

// A 股习惯：红涨绿跌；线条用中性 + 单一金色点缀
const UP_COLOR = '#ff4d4f'
const DOWN_COLOR = '#00b386'
const GOLD = '#d4a958'

const MA_COLORS: Record<string, string> = {
  ma5: '#f2f2f2',
  ma10: GOLD,
  ma20: '#6ea8fe',
  ma60: 'rgba(255,255,255,0.4)',
}

const AXIS_LABEL = { color: 'rgba(255,255,255,0.45)', fontSize: 11 }
const AXIS_LINE = { lineStyle: { color: 'rgba(255,255,255,0.12)' } }
const SPLIT_LINE = { lineStyle: { color: 'rgba(255,255,255,0.06)' } }
const TOOLTIP = {
  backgroundColor: '#14171d',
  borderColor: 'rgba(255,255,255,0.12)',
  borderWidth: 1,
  textStyle: { color: '#f2f2f2' },
  valueFormatter: (value: number | number[]) =>
    Array.isArray(value) ? value.map((v) => fmt(v)) : fmt(value),
}

function fmt(value: unknown): string {
  return typeof value === 'number' ? value.toFixed(2) : String(value ?? '—')
}

const chartEl = ref<HTMLElement | null>(null)
let chart: echarts.ECharts | null = null
let ro: ResizeObserver | null = null

function formatDate(iso: string): string {
  return iso.slice(5) // MM-DD
}

// 按 trade_date 对齐指标，避免 K 线与指标长度不一致时错位
function alignIndicators(items: KlineItem[]): Map<string, IndicatorsItem> {
  const map = new Map<string, IndicatorsItem>()
  for (const row of props.indicators ?? []) map.set(row.trade_date, row)
  return map
}

function buildOption(items: KlineItem[]): echarts.EChartsCoreOption {
  const dates = items.map((item) => formatDate(item.trade_date))
  const rawDates = items.map((item) => item.trade_date)
  const indicatorMap = alignIndicators(items)
  const aligned = rawDates.map((date) => indicatorMap.get(date))

  const hasMa = aligned.some((row) => row && row.ma5 != null)
  const maSeries = Object.keys(MA_COLORS).map((key) => ({
    name: key.toUpperCase(),
    type: 'line' as const,
    xAxisIndex: 0,
    yAxisIndex: 0,
    data: aligned.map((row) => (row ? row[key as keyof IndicatorsItem] : null)),
    symbol: 'none',
    lineStyle: { width: 1, color: MA_COLORS[key] },
    itemStyle: { color: MA_COLORS[key] },
    emphasis: { disabled: true },
  }))

  const macdHist = aligned.map((row, index) => {
    const hist = row?.macd_hist ?? null
    return {
      value: hist,
      itemStyle: {
        color:
          hist == null || items[index].close >= items[index].open
            ? UP_COLOR
            : DOWN_COLOR,
      },
    }
  })

  return {
    animation: false,
    legend: hasMa
      ? {
          top: 0,
          right: 8,
          itemWidth: 14,
          textStyle: { color: 'rgba(255,255,255,0.55)', fontSize: 11 },
          data: ['MA5', 'MA10', 'MA20', 'MA60'],
        }
      : undefined,
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross', label: { backgroundColor: '#1c2129' } },
      ...TOOLTIP,
      confine: true,
      position: function (point, _, __, size) {
        return [point[0] + 14, point[1] + 14]
      },
    },
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    grid: [
      { left: 60, right: 20, top: 32, height: '40%' },
      { left: 60, right: 20, top: '62%', height: '11%' },
      { left: 60, right: 20, top: '78%', height: '10%' },
    ],
    xAxis: [
      {
        type: 'category',
        gridIndex: 0,
        data: dates,
        boundaryGap: true,
        axisLine: AXIS_LINE,
        axisLabel: { show: false },
        axisTick: { show: false },
      },
      {
        type: 'category',
        gridIndex: 1,
        data: dates,
        axisLine: AXIS_LINE,
        axisLabel: { show: false },
        axisTick: { show: false },
      },
      {
        type: 'category',
        gridIndex: 2,
        data: dates,
        axisLine: AXIS_LINE,
        axisLabel: AXIS_LABEL,
        axisTick: { show: false },
      },
    ],
    yAxis: [
      {
        type: 'value',
        gridIndex: 0,
        scale: true,
        axisLabel: AXIS_LABEL,
        splitLine: SPLIT_LINE,
      },
      {
        type: 'value',
        gridIndex: 1,
        axisLabel: { show: false },
        splitLine: { show: false },
      },
      {
        type: 'value',
        gridIndex: 2,
        scale: true,
        axisLabel: { show: false },
        splitLine: { show: false },
      },
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0, 1, 2], start: 55, end: 100 },
      { type: 'slider', xAxisIndex: [0, 1, 2], start: 55, end: 100, bottom: 4, height: 16 },
    ],
    series: [
      {
        name: 'K线',
        type: 'candlestick',
        xAxisIndex: 0,
        yAxisIndex: 0,
        data: items.map((item) => [item.open, item.close, item.low, item.high]),
        itemStyle: {
          color: UP_COLOR,
          color0: DOWN_COLOR,
          borderColor: UP_COLOR,
          borderColor0: DOWN_COLOR,
        },
      },
      ...maSeries,
      {
        name: '成交量',
        type: 'bar',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: items.map((item, index) => ({
          value: item.volume,
          itemStyle: {
            color: item.close >= items[index].open ? UP_COLOR : DOWN_COLOR,
          },
        })),
        barMaxWidth: 12,
      },
      {
        name: 'MACD',
        type: 'line',
        xAxisIndex: 2,
        yAxisIndex: 2,
        data: aligned.map((row) => row?.macd ?? null),
        symbol: 'none',
        lineStyle: { width: 1, color: '#f2f2f2' },
        itemStyle: { color: '#f2f2f2' },
        emphasis: { disabled: true },
      },
      {
        name: 'DEA',
        type: 'line',
        xAxisIndex: 2,
        yAxisIndex: 2,
        data: aligned.map((row) => row?.macd_signal ?? null),
        symbol: 'none',
        lineStyle: { width: 1, color: GOLD },
        itemStyle: { color: GOLD },
        emphasis: { disabled: true },
      },
      {
        name: 'MACD柱',
        type: 'bar',
        xAxisIndex: 2,
        yAxisIndex: 2,
        data: macdHist,
        barMaxWidth: 6,
      },
    ],
  }
}

function render() {
  if (!chart) return
  chart.setOption(buildOption(props.items), true)
}

function resize() {
  chart?.resize()
}

onMounted(() => {
  if (chartEl.value) {
    chart = echarts.init(chartEl.value)
    render()
    window.addEventListener('resize', resize)
    ro = new ResizeObserver(resize)
    ro.observe(chartEl.value)
  }
})

watch(() => [props.items, props.indicators], render)

onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  ro?.disconnect()
  ro = null
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div ref="chartEl" class="kline-chart" />
</template>

<style scoped>
.kline-chart {
  width: 100%;
  height: 100%;
  min-height: 420px;
}

@media (max-width: 760px) {
  .kline-chart {
    min-height: 360px;
  }
}
</style>
