<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { mockKline } from '../mocks/stock'
import type { KlineItem } from '../types/api'
import * as echarts from 'echarts/core'
import { CandlestickChart } from 'echarts/charts'
import { GridComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([CandlestickChart, GridComponent, CanvasRenderer])

const router = useRouter()
const chartRef = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null

// 用 mock K 线末尾 60 条画迷你走势图
const kline = mockKline().data.slice(-60)

function initChart() {
  if (!chartRef.value) return
  chart = echarts.init(chartRef.value)
  chart.setOption({
    grid: { left: 0, right: 0, top: 0, bottom: 0 },
    xAxis: { type: 'category', show: false },
    yAxis: { type: 'value', show: false, scale: true },
    series: [
      {
        type: 'candlestick',
        data: kline.map((k: KlineItem) => [k.open, k.close, k.low, k.high]),
        itemStyle: {
          color: '#ff4d4f',
          color0: '#00b386',
          borderColor: '#ff4d4f',
          borderColor0: '#00b386',
        },
      },
    ],
  })
}

const stats = [
  { label: '上证指数', value: '3,245.67', change: '+0.54%', up: true },
  { label: '深证成指', value: '10,892.31', change: '-0.23%', up: false },
  { label: '创业板指', value: '2,156.89', change: '+1.12%', up: true },
]

const features = [
  { title: 'K 线分析', desc: '蜡烛图 + MA/MACD/BOLL 多指标叠加', icon: 'lines' },
  { title: 'AI 投研', desc: '大模型读取真实数据生成分析报告', icon: 'ai' },
  { title: '策略回测', desc: '收益率 / 最大回撤 / 夏普率', icon: 'chart' },
]

function goDemo() {
  router.push('/stock/600519')
}

onMounted(() => {
  initChart()
  window.addEventListener('resize', resize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  chart?.dispose()
})

function resize() {
  chart?.resize()
}
</script>

<template>
  <main class="landing">
    <!-- 英雄区 -->
    <section class="hero">
      <div class="hero-content">
        <p class="eyebrow">AI QUANT RESEARCH · V1</p>
        <h1>AI 量化投研平台</h1>
        <p class="subtitle">真实行情 · 技术指标 · 量化评分 · 策略回测 · AI 报告</p>
      </div>

      <!-- 迷你 K 线装饰 -->
      <div class="hero-chart">
        <div ref="chartRef" class="mini-chart"></div>
      </div>

      <!-- 三个指数 -->
      <div class="index-row">
        <div v-for="s in stats" :key="s.label" class="index-item">
          <span class="idx-label">{{ s.label }}</span>
          <span class="idx-value">{{ s.value }}</span>
          <span :class="['idx-change', s.up ? 'up' : 'down']">
            {{ s.change }}
          </span>
        </div>
      </div>
    </section>

    <!-- 功能入口卡片 -->
    <section class="features">
      <button
        v-for="f in features"
        :key="f.title"
        type="button"
        class="feature-card"
        @click="goDemo"
      >
        <span :class="['feature-icon', f.icon]"></span>
        <div>
          <h3>{{ f.title }}</h3>
          <p>{{ f.desc }}</p>
        </div>
      </button>
    </section>

    <p class="footer-hint">在顶部搜索栏输入股票代码或名称开始 →</p>
  </main>
</template>

<style scoped>
.landing {
  display: flex;
  flex-direction: column;
  align-items: center;
  min-height: calc(100vh - 52px);
  padding: 56px 24px 32px;
}

/* 英雄区 */
.hero {
  width: min(860px, 100%);
  text-align: center;
}

.hero-content {
  margin-bottom: 28px;
}

.eyebrow {
  margin: 0 0 14px;
  color: var(--text-faint, rgba(255, 255, 255, 0.38));
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

h1 {
  margin: 0 0 10px;
  font-size: clamp(30px, 4.5vw, 42px);
  font-weight: 700;
  line-height: 1.15;
  color: rgba(255, 255, 255, 0.92);
  letter-spacing: 0.01em;
}

.subtitle {
  margin: 0;
  color: rgba(255, 255, 255, 0.42);
  font-size: 14px;
  letter-spacing: 0.04em;
}

/* 迷你 K 线装饰 */
.hero-chart {
  width: 100%;
  height: 120px;
  margin-bottom: 20px;
  border: 1px solid rgba(255, 255, 255, 0.05);
  border-radius: 8px;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.02);
}

.mini-chart {
  width: 100%;
  height: 100%;
}

/* 三个指数 */
.index-row {
  display: flex;
  justify-content: center;
  gap: 32px;
  margin-bottom: 48px;
}

.index-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.idx-label {
  color: rgba(255, 255, 255, 0.32);
  font-size: 11px;
  letter-spacing: 0.06em;
}

.idx-value {
  color: rgba(255, 255, 255, 0.88);
  font-size: 17px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.idx-change {
  font-size: 12px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.idx-change.up {
  color: var(--up, #ff4d4f);
}

.idx-change.down {
  color: var(--down, #00b386);
}

/* 功能卡片 */
.features {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
  width: min(860px, 100%);
  margin-bottom: 28px;
}

.feature-card {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 20px;
  border: 1px solid rgba(255, 255, 255, 0.05);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.02);
  cursor: pointer;
  font: inherit;
  color: inherit;
  text-align: left;
  transition:
    border-color 0.15s ease,
    background 0.15s ease;
}

.feature-card:hover {
  border-color: rgba(255, 255, 255, 0.14);
  background: rgba(255, 255, 255, 0.04);
}

.feature-icon {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  flex-shrink: 0;
  position: relative;
}

/* K 线图标 */
.feature-icon.lines {
  background: linear-gradient(
    135deg,
    rgba(255, 77, 79, 0.15),
    rgba(0, 179, 134, 0.15)
  );
  border: 1px solid rgba(255, 255, 255, 0.08);
}

.feature-icon.lines::before {
  content: '';
  position: absolute;
  left: 4px;
  top: 50%;
  width: 20px;
  height: 1.5px;
  background: var(--accent, #d4a958);
  transform: translateY(-50%);
}

/* AI 图标 */
.feature-icon.ai {
  background: rgba(212, 169, 88, 0.1);
  border: 1px solid rgba(212, 169, 88, 0.25);
}

.feature-icon.ai::before {
  content: 'AI';
  position: absolute;
  left: 0;
  top: 0;
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  font-weight: 700;
  color: var(--accent, #d4a958);
}

/* 回测图标 */
.feature-icon.chart {
  background: rgba(0, 179, 134, 0.08);
  border: 1px solid rgba(0, 179, 134, 0.2);
}

.feature-icon.chart::before {
  content: '';
  position: absolute;
  left: 4px;
  bottom: 4px;
  width: 3px;
  height: 12px;
  background: rgba(0, 179, 134, 0.6);
  border-radius: 1px;
}

.feature-icon.chart::after {
  content: '';
  position: absolute;
  left: 10px;
  bottom: 4px;
  width: 3px;
  height: 18px;
  background: rgba(0, 179, 134, 0.8);
  border-radius: 1px;
}

.feature-card h3 {
  margin: 0 0 4px;
  font-size: 14px;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.88);
}

.feature-card p {
  margin: 0;
  font-size: 12px;
  line-height: 1.5;
  color: rgba(255, 255, 255, 0.42);
}

.footer-hint {
  color: rgba(255, 255, 255, 0.28);
  font-size: 12px;
  letter-spacing: 0.04em;
}

@media (max-width: 760px) {
  .features {
    grid-template-columns: 1fr;
  }

  .index-row {
    flex-direction: column;
    gap: 12px;
  }
}
</style>
