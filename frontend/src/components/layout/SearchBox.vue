<script setup lang="ts">
// 顶栏搜索框：输入联想下拉，点击直达工作台
import { ref } from 'vue'
import { useRouter } from 'vue-router'

import { searchStocks } from '../../api/stocks'
import type { StockBrief } from '../../types/api'

const router = useRouter()

const keyword = ref('')
const results = ref<StockBrief[]>([])
const searching = ref(false)
const showDropdown = ref(false)

async function onSearch() {
  if (!keyword.value.trim()) return
  searching.value = true
  try {
    const res = await searchStocks(keyword.value)
    results.value = res.data
    showDropdown.value = results.value.length > 0
  } catch {
    results.value = []
  } finally {
    searching.value = false
  }
}

function goDetail(stock: StockBrief) {
  keyword.value = ''
  showDropdown.value = false
  router.push(`/stock/${stock.stock_code}`)
}

function onBlur() {
  // 延迟关闭，让 click 事件先触发
  setTimeout(() => (showDropdown.value = false), 200)
}
</script>

<template>
  <div class="search-wrapper">
    <el-input
      v-model="keyword"
      placeholder="搜索股票代码或名称…"
      class="search-input"
      clearable
      @input="onSearch"
      @focus="showDropdown = results.length > 0"
      @blur="onBlur"
    >
      <template #prefix>
        <span class="search-icon">⌕</span>
      </template>
    </el-input>
    <ul v-if="showDropdown && results.length > 0" class="search-dropdown">
      <li v-for="stock in results.slice(0, 8)" :key="stock.stock_code">
        <button type="button" class="dropdown-item" @click="goDetail(stock)">
          <span class="dd-name">{{ stock.stock_name }}</span>
          <span class="dd-code">{{ stock.stock_code }}</span>
        </button>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.search-wrapper {
  position: relative;
  width: 100%;
}

.search-input :deep(.el-input__wrapper) {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 6px;
  box-shadow: none;
  height: 34px;
  transition:
    border-color 0.15s ease,
    background 0.15s ease;
}

.search-input :deep(.el-input__wrapper:hover) {
  border-color: var(--border-strong);
}

.search-input :deep(.el-input__wrapper.is-focus) {
  border-color: var(--accent);
  background: var(--surface);
}

.search-input :deep(.el-input__inner) {
  color: var(--text-main);
  font-size: 13px;
}

.search-input :deep(.el-input__inner::placeholder) {
  color: var(--text-faint);
}

.search-icon {
  color: var(--text-faint);
  font-size: 15px;
}

.search-dropdown {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  right: 0;
  list-style: none;
  margin: 0;
  padding: 4px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  box-shadow: var(--shadow-md);
  z-index: 200;
}

.dropdown-item {
  display: flex;
  width: 100%;
  box-sizing: border-box;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  border: none;
  border-radius: 4px;
  background: transparent;
  cursor: pointer;
  font: inherit;
  color: var(--text-main);
  transition: background 0.12s ease;
}

.dropdown-item:hover {
  background: var(--surface-hover);
}

.dd-name {
  font-size: 13px;
  font-weight: 500;
}

.dd-code {
  color: var(--text-faint);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}
</style>
