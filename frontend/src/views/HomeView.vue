<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

import type { KlineItem } from '../types/api'
import { mockKline } from '../mocks/stock'
import SearchBox from '../components/layout/SearchBox.vue'
import { useThemeStore } from '../stores/theme'
import { chartPalette, hexToRgba } from '../utils/chartTheme'
import * as echarts from 'echarts/core'
import { CandlestickChart } from 'echarts/charts'
import { GridComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([CandlestickChart, GridComponent, CanvasRenderer])

const theme = useThemeStore()
const bgRef = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null

// 背景蜡烛颜色随主题适配：亮色主题降低透明度，避免被白色遮罩压得失真
function candleColors() {
  const p = chartPalette()
  const alpha = theme.isDark ? 0.8 : 0.5
  return { up: hexToRgba(p.up, alpha), down: hexToRgba(p.down, alpha) }
}

function applyColors() {
  if (!chart) return
  const c = candleColors()
  chart.setOption({
    series: [
      {
        itemStyle: {
          color: c.up,
          color0: c.down,
          borderColor: c.up,
          borderColor0: c.down,
        },
      },
    ],
  })
}

function initBg() {
  if (!bgRef.value) return
  chart = echarts.init(bgRef.value)
  const all = mockKline().data
  // 复制两份数据，首尾相连实现无缝循环
  const kline: KlineItem[] = []
  while (kline.length < 480) {
    kline.push(...all)
  }
  const data = kline.slice(0, 480).map((k) => [k.open, k.close, k.low, k.high])

  chart.setOption({
    grid: { left: 0, right: 0, top: 0, bottom: 0 },
    xAxis: { type: 'category', show: false, boundaryGap: false },
    yAxis: { type: 'value', show: false, scale: true },
    series: [{ type: 'candlestick', data }],
    animation: false,
  })
  applyColors()
}

function resize() {
  chart?.resize()
}

onMounted(() => {
  initBg()
  window.addEventListener('resize', resize)
  // 主题切换后 CSS 变量变化，需重建蜡烛配色
  watch(() => theme.theme, applyColors)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  chart?.dispose()
})
</script>

<template>
  <main class="landing">
    <!-- 背景动画 K 线 -->
    <div class="bg-scroll">
      <div ref="bgRef" class="bg-chart"></div>
    </div>
    <div class="bg-overlay"></div>

    <!-- 居中内容 -->
    <div class="center">
      <h1>DeepInSight</h1>
      <p class="subtitle">行情回放 · 技术指标 · 量化评分 · 策略回测 · AI 报告</p>
      <p class="scope-note">冻结样本演示 · 仅 600519 贵州茅台 · 样本区间 2025-01-02 ~ 2026-08-31</p>

      <!-- 大号搜索框：输入即联想，点击结果直达工作台 -->
      <div class="hero-search">
        <SearchBox />
      </div>
    </div>
  </main>
</template>

<style scoped>
.landing {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  /* 在工作台外壳内容区内铺满一屏（扣除顶栏高度） */
  min-height: calc(100vh - var(--header-height));
  overflow: hidden;
}

/* 背景滚动容器：宽度 200%，GPU 加速 */
.bg-scroll {
  position: absolute;
  top: 0;
  left: 0;
  width: 200%;
  height: 100%;
  z-index: 0;
  will-change: transform;
  animation: scroll-kline 40s linear infinite;
}

.bg-chart {
  width: 100%;
  height: 100%;
}

@keyframes scroll-kline {
  from {
    transform: translateX(0);
  }
  to {
    transform: translateX(-50%);
  }
}

/* 遮罩：纵向渐变压暗背景 + 两处微光（暗色默认） */
.bg-overlay {
  position: absolute;
  inset: 0;
  z-index: 1;
  background:
    linear-gradient(
      180deg,
      rgba(9, 9, 11, 0.4) 0%,
      rgba(9, 9, 11, 0.65) 40%,
      rgba(9, 9, 11, 0.85) 70%,
      rgba(9, 9, 11, 0.95) 100%
    ),
    radial-gradient(
      ellipse at 30% 20%,
      rgba(59, 130, 246, 0.06) 0%,
      transparent 50%
    ),
    radial-gradient(
      ellipse at 70% 80%,
      rgba(59, 130, 246, 0.04) 0%,
      transparent 50%
    );
}

[data-theme='light'] .bg-overlay {
  background:
    linear-gradient(
      180deg,
      rgba(250, 250, 250, 0.45) 0%,
      rgba(250, 250, 250, 0.7) 40%,
      rgba(250, 250, 250, 0.88) 70%,
      rgba(250, 250, 250, 0.96) 100%
    ),
    radial-gradient(
      ellipse at 30% 20%,
      rgba(37, 99, 235, 0.06) 0%,
      transparent 50%
    ),
    radial-gradient(
      ellipse at 70% 80%,
      rgba(37, 99, 235, 0.04) 0%,
      transparent 50%
    );
}

/* 居中内容 */
.center {
  position: relative;
  z-index: 2;
  width: min(560px, 90%);
  text-align: center;
}

h1 {
  margin: 0 0 10px;
  font-family: var(--font-brand);
  font-size: clamp(36px, 5.5vw, 50px);
  font-weight: 700;
  line-height: 1.15;
  letter-spacing: 0.015em;
  /* 品牌名跟随主题色：accent → accent-hover 斜向渐变文字 */
  background: linear-gradient(120deg, var(--accent) 20%, var(--accent-hover) 90%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  -webkit-text-fill-color: transparent;
}

.subtitle {
  margin: 0 0 12px;
  color: var(--text-sub);
  font-size: 14px;
  letter-spacing: 0.06em;
}

/* 演示范围说明：降级为小字灰调，不抢主 CTA 视觉权重 */
.scope-note {
  margin: 0 0 28px;
  color: var(--text-faint);
  font-size: 12px;
  letter-spacing: 0.04em;
  line-height: 1.6;
}

/* hero 搜索框：比顶栏更大更醒目，浮在背景上带柔和阴影；聚焦时accent描边 + 柔光圈 */
.hero-search {
  width: min(420px, 100%);
  margin: 0 auto;
}

.hero-search :deep(.el-input__wrapper) {
  height: 46px;
  border-radius: 10px;
  background: var(--surface);
  border-color: var(--border-strong);
  box-shadow: var(--shadow-md);
}

.hero-search :deep(.el-input__inner) {
  font-size: 14px;
}

.hero-search :deep(.el-input__wrapper.is-focus) {
  border-color: var(--accent);
  box-shadow:
    0 0 0 3px var(--accent-bg),
    var(--shadow-md);
}
</style>
