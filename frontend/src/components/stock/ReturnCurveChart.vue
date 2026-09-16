<script setup lang="ts">
// 累计收益率曲线：equity 为绝对权益，展示换算 ret = equity / initial_cash - 1
// V2 支持叠加基准曲线（买入持有基准，不含成本——C 契约要求标注）
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart, type LineSeriesOption } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

import type { BenchmarkCurvePoint } from '../../types/api'

echarts.use([LineChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

const props = defineProps<{
  equityCurve: Array<{ trade_date: string; equity: number }>
  benchmarkCurve?: BenchmarkCurvePoint[] | null
  initialCash: number
}>()

// 以权益曲线日期为轴，基准按日期对齐（契约：两曲线同覆盖回测区间有效交易日）
const series = computed(() => {
  const cash = props.initialCash
  const dates = props.equityCurve.map((p) => p.trade_date)
  const equityRet = props.equityCurve.map((p) => (cash ? p.equity / cash - 1 : 0))
  let benchRet: Array<number | null> | null = null
  if (props.benchmarkCurve && props.benchmarkCurve.length > 0 && cash) {
    const map = new Map(props.benchmarkCurve.map((p) => [p.trade_date, p.benchmark_equity]))
    benchRet = dates.map((d) => {
      const v = map.get(d)
      return v == null ? null : v / cash - 1
    })
  }
  return { dates, equityRet, benchRet }
})

const chartEl = ref<HTMLElement | null>(null)
let chart: echarts.ECharts | null = null

function render() {
  if (!chart) return
  const seriesList: LineSeriesOption[] = [
    {
      name: '策略累计收益',
      type: 'line',
      data: series.value.equityRet,
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
  ]
  if (series.value.benchRet) {
    seriesList.push({
      name: '买入持有基准（不含成本）',
      type: 'line',
      data: series.value.benchRet,
      symbol: 'none',
      lineStyle: { width: 1.2, color: 'rgba(255,255,255,0.45)', type: 'dashed' },
      itemStyle: { color: 'rgba(255,255,255,0.45)' },
    })
  }
  chart.setOption(
    {
      animation: false,
      tooltip: {
        trigger: 'axis',
        backgroundColor: '#14171d',
        borderColor: 'rgba(255,255,255,0.12)',
        borderWidth: 1,
        textStyle: { color: '#f2f2f2' },
        valueFormatter: (value: number | null) =>
          value == null ? '—' : `${(value * 100).toFixed(2)}%`,
      },
      legend: series.value.benchRet
        ? {
            top: 0,
            right: 0,
            textStyle: { color: 'rgba(255,255,255,0.5)', fontSize: 11 },
            itemWidth: 16,
            itemHeight: 8,
          }
        : undefined,
      grid: { left: 52, right: 12, top: series.value.benchRet ? 28 : 12, bottom: 24 },
      xAxis: {
        type: 'category',
        data: series.value.dates.map((d) => d.slice(5)),
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
      series: seriesList,
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

watch(series, render)

onBeforeUnmount(() => {
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div ref="chartEl" class="curve-chart" />
</template>

<style scoped>
.curve-chart {
  width: 100%;
  height: 100%;
}
</style>
