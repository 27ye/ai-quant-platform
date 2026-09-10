<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'

import { searchStocks } from '../api/stocks'
import type { StockBrief } from '../types/api'

const router = useRouter()
const keyword = ref('')
const results = ref<StockBrief[]>([])
const loading = ref(false)
const searched = ref(false)

async function onSearch() {
  if (!keyword.value.trim()) return
  loading.value = true
  try {
    const res = await searchStocks(keyword.value)
    results.value = res.data
    searched.value = true
  } catch {
    results.value = []
  } finally {
    loading.value = false
  }
}

function goDetail(stock: StockBrief) {
  router.push(`/stock/${stock.stock_code}`)
}
</script>

<template>
  <main class="landing">
    <section class="hero">
      <p class="eyebrow">AI Quant Research · V1</p>
      <h1>搜索股票，获取 AI 投研分析</h1>
      <p class="subtitle">真实 K 线 · 技术指标 · 量化评分 · 策略回测 · AI 报告</p>

      <div class="search-box">
        <el-input
          v-model="keyword"
          size="large"
          placeholder="输入股票代码或名称，如 600519 / 茅台"
          clearable
          @keyup.enter="onSearch"
        >
          <template #append>
            <el-button :loading="loading" @click="onSearch">搜索</el-button>
          </template>
        </el-input>
      </div>

      <el-empty
        v-if="searched && results.length === 0"
        description="没有找到匹配的股票"
      />

      <ul v-else-if="results.length > 0" class="result-list">
        <li v-for="stock in results" :key="stock.stock_code">
          <button type="button" class="result-item" @click="goDetail(stock)">
            <span class="stock-name">{{ stock.stock_name }}</span>
            <span class="stock-code">{{ stock.stock_code }}</span>
          </button>
        </li>
      </ul>
    </section>
  </main>
</template>

<style scoped>
.landing {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: calc(100vh - 52px);
  padding: 48px 24px;
}

.hero {
  width: min(640px, 100%);
  text-align: center;
}

.eyebrow {
  margin: 0 0 16px;
  color: var(--text-faint, rgba(255, 255, 255, 0.38));
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

h1 {
  margin: 0 0 12px;
  font-size: clamp(28px, 4vw, 40px);
  font-weight: 700;
  line-height: 1.2;
  color: rgba(255, 255, 255, 0.92);
}

.subtitle {
  margin: 0 0 36px;
  color: rgba(255, 255, 255, 0.48);
  font-size: 15px;
  line-height: 1.6;
}

.search-box {
  text-align: left;
}

.search-box :deep(.el-input__wrapper) {
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 8px;
  box-shadow: none;
}

.search-box :deep(.el-input__wrapper:hover) {
  border-color: rgba(255, 255, 255, 0.14);
}

.search-box :deep(.el-input__wrapper.is-focus) {
  border-color: var(--accent, #d4a958);
}

.search-box :deep(.el-input-group__append) {
  background: var(--accent, #d4a958);
  border: 1px solid var(--accent, #d4a958);
  border-radius: 0 8px 8px 0;
}

.search-box :deep(.el-input-group__append .el-button) {
  color: #1a1a1a;
  font-weight: 600;
}

.result-list {
  list-style: none;
  margin: 24px 0 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.result-item {
  display: flex;
  width: 100%;
  box-sizing: border-box;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 6px;
  background: transparent;
  cursor: pointer;
  font: inherit;
  color: inherit;
  transition:
    border-color 0.12s ease,
    background 0.12s ease;
}

.result-item:hover {
  border-color: rgba(255, 255, 255, 0.16);
  background: rgba(255, 255, 255, 0.03);
}

.stock-name {
  font-weight: 500;
}

.stock-code {
  color: rgba(255, 255, 255, 0.38);
  font-variant-numeric: tabular-nums;
}

@media (max-width: 760px) {
  .result-list {
    grid-template-columns: 1fr;
  }
}
</style>
