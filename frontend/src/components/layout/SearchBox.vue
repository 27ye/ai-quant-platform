<script setup lang="ts">
// 顶栏搜索框：输入联想下拉，点击直达工作台
import { ref } from 'vue'
import { useRouter } from 'vue-router'

import { searchStocks } from '../../api/stocks'
import type { StockBrief } from '../../types/api'
import { useHealthStore } from '../../stores/health'

const router = useRouter()
const health = useHealthStore()

const keyword = ref('')
const results = ref<StockBrief[]>([])
const searching = ref(false)
const showDropdown = ref(false)
// 是否已发起过搜索：用于空结果时展开提示而非静默
const searched = ref(false)

async function onSearch() {
  const kw = keyword.value.trim()
  if (!kw) {
    // 清空关键词时同步收起下拉
    results.value = []
    searched.value = false
    showDropdown.value = false
    return
  }
  searching.value = true
  try {
    const res = await searchStocks(kw)
    results.value = res.data
    searched.value = true
    // 空结果也展开下拉，由提示文案说明冻结演示范围
    showDropdown.value = true
  } catch {
    results.value = []
    showDropdown.value = false
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
      @focus="showDropdown = searched && keyword.trim().length > 0"
      @blur="onBlur"
    >
      <template #prefix>
        <span class="search-icon">⌕</span>
      </template>
    </el-input>
    <ul v-if="showDropdown" class="search-dropdown">
      <template v-if="results.length > 0">
        <li v-for="stock in results.slice(0, 8)" :key="stock.stock_code">
          <button type="button" class="dropdown-item" @click="goDetail(stock)">
            <span class="dd-name">{{ stock.stock_name }}</span>
            <span class="dd-code">{{ stock.stock_code }}</span>
          </button>
        </li>
      </template>
      <li v-else class="dropdown-empty">{{ health.acceptanceMode === 'frozen' ? '冻结演示仅包含 600519，未命中其他股票' : '没有找到匹配的股票' }}</li>
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

/* 空结果提示：冻结演示范围说明，替代空白列表 */
.dropdown-empty {
  padding: 10px 12px;
  color: var(--text-faint);
  font-size: 12px;
  text-align: center;
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
