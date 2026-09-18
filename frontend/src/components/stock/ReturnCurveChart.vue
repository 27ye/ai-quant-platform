<script setup lang="ts">
// 累计收益率曲线：equity 为绝对权益，展示换算 ret = equity / initial_cash - 1
// V2 支持叠加基准曲线（买入持有基准，不含成本——C 契约要求标注）
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart, type LineSeriesOption } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

import type { BenchmarkCurvePoint } from '../../types/api'
import { useThemeStore } from '../../stores/theme'
import { chartPalette, hexToRgba } from '../../utils/chartTheme'

echarts.use([LineChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

const props = defineProps<{
  equityCurve: Array<{ trade_date: string; equity: number }>
  benchmarkCurve?: BenchmarkCurvePoint[] | null
  initialCash: number
}>()

const theme = useThemeStore()

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
  // 每次渲染从 CSS 变量取色，主题切换后重建即可生效
  const pal = chartPalette()
  const seriesList: LineSeriesOption[] = [
    {
      name: '策略累计收益',
      type: 'line',
      data: series.value.equityRet,
      symbol: 'none',
      lineStyle: { width: 1.5, color: pal.accent },
      itemStyle: { color: pal.accent },
      areaStyle: {
        color: {
          type: 'linear',
          x: 0,
          y: 0,
          x2: 0,
          y2: 1,
          colorStops: [
            { offset: 0, color: hexToRgba(pal.accent, 0.16) },
            { offset: 1, color: hexToRgba(pal.accent, 0) },
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
      lineStyle: { width: 1.2, color: pal.textFaint, type: 'dashed' },
      itemStyle: { color: pal.textFaint },
    })
  }
  chart.setOption(
    {
      animation: false,
      tooltip: {
        trigger: 'axis',
        backgroundColor: pal.surface,
        borderColor: pal.borderStrong,
        borderWidth: 1,
        textStyle: { color: pal.textMain },
        valueFormatter: (value: number | null) =>
          value == null ? '—' : `${(value * 100).toFixed(2)}%`,
      },
      legend: series.value.benchRet
        ? {
            top: 0,
            right: 0,
            textStyle: { color: pal.textSub, fontSize: 11 },
            itemWidth: 16,
            itemHeight: 8,
          }
        : undefined,
      grid: { left: 52, right: 12, top: series.value.benchRet ? 28 : 12, bottom: 24 },
      xAxis: {
        type: 'category',
        data: series.value.dates.map((d) => d.slice(5)),
        axisLabel: { color: pal.textFaint, fontSize: 11 },
        axisLine: { lineStyle: { color: pal.borderStrong } },
        axisTick: { show: false },
      },
      yAxis: {
        type: 'value',
        scale: true,
        axisLabel: {
          color: pal.textFaint,
          fontSize: 11,
          formatter: (value: number) => `${(value * 100).toFixed(0)}%`,
        },
        splitLine: { lineStyle: { color: pal.border } },
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
// 主题/强调色切换：重建 option 应用新调色板
watch(() => [theme.theme, theme.accent], render)

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
