<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { searchStocks } from '../api/stocks'
import type { StockBrief, KlineItem } from '../types/api'
import { mockKline } from '../mocks/stock'
import * as echarts from 'echarts/core'
import { CandlestickChart } from 'echarts/charts'
import { GridComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([CandlestickChart, GridComponent, CanvasRenderer])

const router = useRouter()
const bgRef = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null

// 搜索
const keyword = ref('')
const results = ref<StockBrief[]>([])
const loading = ref(false)
const showDropdown = ref(false)

async function onSearch() {
  if (!keyword.value.trim()) return
  loading.value = true
  try {
    const res = await searchStocks(keyword.value)
    results.value = res.data
    showDropdown.value = results.value.length > 0
  } catch {
    results.value = []
  } finally {
    loading.value = false
  }
}

function goDetail(stock: StockBrief) {
  keyword.value = ''
  showDropdown.value = false
  router.push(`/stock/${stock.stock_code}`)
}

function onBlur() {
  setTimeout(() => (showDropdown.value = false), 200)
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
          color: '#ff4d4f',
          color0: '#00b386',
          borderColor: '#ff4d4f',
          borderColor0: '#00b386',
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

    <!-- 居中内容 -->
    <div class="center">
      <h1>AI 量化投研平台</h1>
      <p class="subtitle">真实行情 · 技术指标 · 量化评分 · 策略回测 · AI 报告</p>

      <div class="search-box">
        <el-input
          v-model="keyword"
          size="large"
          placeholder="输入股票代码或名称，如 600519 / 茅台"
          clearable
          @input="onSearch"
          @focus="showDropdown = results.length > 0"
          @blur="onBlur"
        >
          <template #prefix>
            <span class="search-icon">⌕</span>
          </template>
        </el-input>

        <ul v-if="showDropdown && results.length > 0" class="dropdown">
          <li v-for="stock in results.slice(0, 8)" :key="stock.stock_code">
            <button type="button" class="dd-item" @click="goDetail(stock)">
              <span class="dd-name">{{ stock.stock_name }}</span>
              <span class="dd-code">{{ stock.stock_code }}</span>
            </button>
          </li>
        </ul>
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
  min-height: calc(100vh - 52px);
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

.bg-overlay {
  position: absolute;
  inset: 0;
  z-index: 1;
  background:
    linear-gradient(
      180deg,
      rgba(14, 17, 22, 0.4) 0%,
      rgba(14, 17, 22, 0.65) 40%,
      rgba(14, 17, 22, 0.85) 70%,
      rgba(14, 17, 22, 0.95) 100%
    ),
    radial-gradient(
      ellipse at 30% 20%,
      rgba(212, 169, 88, 0.05) 0%,
      transparent 50%
    ),
    radial-gradient(
      ellipse at 70% 80%,
      rgba(58, 123, 213, 0.04) 0%,
      transparent 50%
    );
  backdrop-filter: blur(4px);
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
  color: rgba(255, 255, 255, 0.95);
  letter-spacing: 0.01em;
}

.subtitle {
  margin: 0 0 40px;
  color: rgba(255, 255, 255, 0.5);
  font-size: 14px;
  letter-spacing: 0.06em;
}

/* 搜索框 */
.search-box {
  position: relative;
  text-align: left;
}

.search-box :deep(.el-input__wrapper) {
  background: rgba(20, 23, 29, 0.85);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 8px;
  box-shadow: 0 4px 24px rgba(0, 0, 0, 0.35);
  height: 44px;
}

.search-box :deep(.el-input__wrapper:hover) {
  border-color: rgba(255, 255, 255, 0.18);
}

.search-box :deep(.el-input__wrapper.is-focus) {
  border-color: var(--accent, #d4a958);
  box-shadow: 0 4px 24px rgba(0, 0, 0, 0.35), 0 0 0 2px rgba(212, 169, 88, 0.12);
}

.search-box :deep(.el-input__inner) {
  color: rgba(255, 255, 255, 0.88);
  font-size: 15px;
}

.search-box :deep(.el-input__inner::placeholder) {
  color: rgba(255, 255, 255, 0.32);
}

.search-icon {
  color: rgba(255, 255, 255, 0.3);
  font-size: 16px;
}

.dropdown {
  position: absolute;
  top: calc(100% + 6px);
  left: 0;
  right: 0;
  list-style: none;
  margin: 0;
  padding: 4px;
  background: #181c23;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 8px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
  z-index: 200;
}

.dd-item {
  display: flex;
  width: 100%;
  box-sizing: border-box;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  border: none;
  border-radius: 6px;
  background: transparent;
  cursor: pointer;
  font: inherit;
  color: inherit;
  transition: background 0.12s ease;
}

.dd-item:hover {
  background: rgba(255, 255, 255, 0.06);
}

.dd-name {
  font-weight: 500;
}

.dd-code {
  color: rgba(255, 255, 255, 0.38);
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}

@media (prefers-reduced-motion: reduce) {
  .bg-scroll {
    animation: none;
  }
}
</style>
