<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import type { KlineItem } from '../types/api'
import { mockKline } from '../mocks/stock'
import ThemeToggle from '../components/layout/ThemeToggle.vue'
import { useAppContext } from '../stores/appContext'
import { useHealthStore } from '../stores/health'
import * as echarts from 'echarts/core'
import { CandlestickChart } from 'echarts/charts'
import { GridComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([CandlestickChart, GridComponent, CanvasRenderer])

const router = useRouter()
const appContext = useAppContext()
const health = useHealthStore()
const bgRef = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null

// 冻结验收包仅包含 600519；实时工作台继续跟随最近访问的股票。
async function enter() {
  await health.refresh()
  const code = health.acceptanceMode === 'frozen' ? '600519' : appContext.stockCode
  router.push(`/stock/${code}`)
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
    series: [
      {
        type: 'candlestick',
        data,
        itemStyle: {
          color: '#ef4444',
          color0: '#10b981',
          borderColor: '#ef4444',
          borderColor0: '#10b981',
        },
      },
    ],
    animation: false,
  })
}

function resize() {
  chart?.resize()
}

onMounted(() => {
  void health.refresh()
  initBg()
  window.addEventListener('resize', resize)
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

    <!-- 首页无外壳，主题切换浮动在右上角 -->
    <div class="home-toggle">
      <ThemeToggle />
    </div>

    <!-- 居中内容 -->
    <div class="center">
      <h1>DeepInSight</h1>
      <p class="subtitle">真实行情 · 技术指标 · 量化评分 · 策略回测 · AI 报告</p>
      <p v-if="health.acceptanceMode === 'frozen'" class="v1-badge">冻结数据演示 · 仅 600519 贵州茅台</p>
      <p v-else class="v1-badge">V2 投研工作台 · 参数回测与报告历史</p>

      <button type="button" class="entry-btn" @click="enter">
        进入工作台
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M5 12h14" /><path d="m13 6 6 6-6 6" />
        </svg>
      </button>
    </div>
  </main>
</template>

<style scoped>
.landing {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
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
  backdrop-filter: blur(4px);
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

.home-toggle {
  position: absolute;
  top: 16px;
  right: 20px;
  z-index: 3;
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
  font-size: clamp(32px, 5vw, 44px);
  font-weight: 700;
  line-height: 1.15;
  color: var(--text-main);
  letter-spacing: 0.01em;
}

.subtitle {
  margin: 0 0 12px;
  color: var(--text-sub);
  font-size: 14px;
  letter-spacing: 0.06em;
}

/* V1 冻结演示范围标注 */
.v1-badge {
  margin: 0 0 28px;
  padding: 6px 14px;
  display: inline-block;
  background: var(--warn-bg);
  border: 1px solid var(--warn);
  border-radius: 999px;
  color: var(--warn);
  font-size: 12px;
  letter-spacing: 0.04em;
  line-height: 1.5;
}

/* 进入工作台入口按钮 */
.entry-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  height: 44px;
  padding: 0 28px;
  border: none;
  border-radius: 8px;
  background: var(--accent);
  color: #fff;
  font-size: 15px;
  font-weight: 600;
  font-family: inherit;
  letter-spacing: 0.04em;
  cursor: pointer;
  box-shadow: var(--shadow-md);
  transition:
    background 0.15s ease,
    transform 0.15s ease,
    box-shadow 0.15s ease;
}

.entry-btn:hover {
  background: var(--accent-hover);
  transform: translateY(-1px);
  box-shadow: var(--shadow-lg);
}

.entry-btn:active {
  transform: translateY(0);
}

.entry-btn svg {
  transition: transform 0.15s ease;
}

.entry-btn:hover svg {
  transform: translateX(3px);
}
</style>
