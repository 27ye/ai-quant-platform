<script setup lang="ts">
// 顶栏搜索框：防抖联想下拉，点击/回车直达工作台
import { computed, onBeforeUnmount, ref } from 'vue'
import { useRouter } from 'vue-router'

import { searchStocks } from '../../api/stocks'
import type { StockBrief } from '../../types/api'
import { useAppContext } from '../../stores/appContext'
import { useHealthStore } from '../../stores/health'

const router = useRouter()
const health = useHealthStore()
const appContext = useAppContext()

const keyword = ref('')
const results = ref<StockBrief[]>([])
const searching = ref(false)
const showDropdown = ref(false)
// 是否已发起过搜索：用于空结果时展开提示而非静默
const searched = ref(false)
// 请求失败：下拉内展示重试，而不是被拦截器弹 toast
const failed = ref(false)
// 键盘高亮项（-1 表示未选中）
const activeIndex = ref(-1)

// 300ms 防抖 + epoch 过期守卫，避免逐键请求与慢响应覆盖新关键词
let debounceTimer: ReturnType<typeof setTimeout> | null = null
let epoch = 0

const visibleResults = computed(() => results.value.slice(0, 8))

function scheduleSearch() {
  if (debounceTimer) clearTimeout(debounceTimer)
  const kw = keyword.value.trim()
  if (!kw) {
    results.value = []
    searched.value = false
    failed.value = false
    showDropdown.value = false
    activeIndex.value = -1
    return
  }
  debounceTimer = setTimeout(() => runSearch(kw), 300)
}

async function runSearch(kw: string) {
  const currentEpoch = ++epoch
  searching.value = true
  failed.value = false
  try {
    const res = await searchStocks(kw, { skipErrorHandler: true })
    if (currentEpoch !== epoch) return
    results.value = res.data
    // V3 F1：搜索结果顺手登记 code→name（零额外请求），供自选等功能取名称
    appContext.rememberStockNames(res.data)
    searched.value = true
    activeIndex.value = -1
    // 空结果/失败也展开下拉，由提示文案说明
    showDropdown.value = true
  } catch {
    if (currentEpoch !== epoch) return
    results.value = []
    failed.value = true
    showDropdown.value = true
  } finally {
    if (currentEpoch === epoch) searching.value = false
  }
}

function goDetail(stock: StockBrief) {
  keyword.value = ''
  showDropdown.value = false
  activeIndex.value = -1
  router.push(`/stock/${stock.stock_code}`)
}

function onKeydown(event: KeyboardEvent) {
  if (!showDropdown.value || visibleResults.value.length === 0) {
    if (event.key === 'Escape') showDropdown.value = false
    return
  }
  if (event.key === 'ArrowDown') {
    event.preventDefault()
    activeIndex.value = (activeIndex.value + 1) % visibleResults.value.length
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    activeIndex.value =
      activeIndex.value <= 0 ? visibleResults.value.length - 1 : activeIndex.value - 1
  } else if (event.key === 'Enter') {
    const target = visibleResults.value[activeIndex.value]
    if (target) {
      event.preventDefault()
      goDetail(target)
    }
  } else if (event.key === 'Escape') {
    showDropdown.value = false
    activeIndex.value = -1
  }
}

// mousedown 先于 blur 触发，无需延迟关闭的 hack
function onBlur() {
  showDropdown.value = false
}

onBeforeUnmount(() => {
  if (debounceTimer) clearTimeout(debounceTimer)
})
</script>

<template>
  <div class="search-wrapper">
    <el-input
      v-model="keyword"
      placeholder="搜索股票代码或名称…"
      class="search-input"
      clearable
      role="combobox"
      :aria-expanded="showDropdown"
      aria-autocomplete="list"
      aria-controls="search-listbox"
      @input="scheduleSearch"
      @keydown="onKeydown"
      @focus="showDropdown = (searched || failed) && keyword.trim().length > 0"
      @blur="onBlur"
    >
      <template #prefix>
        <span class="search-icon">⌕</span>
      </template>
    </el-input>
    <ul
      v-if="showDropdown"
      id="search-listbox"
      class="search-dropdown"
      role="listbox"
    >
      <template v-if="visibleResults.length > 0">
        <li v-for="(stock, index) in visibleResults" :key="stock.stock_code" role="option" :aria-selected="index === activeIndex">
          <button
            type="button"
            class="dropdown-item"
            :class="{ active: index === activeIndex }"
            @mousedown.prevent="goDetail(stock)"
            @mouseenter="activeIndex = index"
          >
            <span class="dd-name">{{ stock.stock_name }}</span>
            <span class="dd-code">{{ stock.stock_code }}</span>
          </button>
        </li>
      </template>
      <li v-else-if="failed" class="dropdown-empty">
        搜索失败，请稍后重试
        <button type="button" class="dd-retry" @mousedown.prevent="runSearch(keyword.trim())">
          重试
        </button>
      </li>
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

.dropdown-item:hover,
.dropdown-item.active {
  background: var(--surface-hover);
}

/* 空结果/失败提示 */
.dropdown-empty {
  padding: 10px 12px;
  color: var(--text-faint);
  font-size: 12px;
  text-align: center;
}

.dd-retry {
  margin-left: 6px;
  padding: 0;
  border: none;
  background: none;
  color: var(--accent);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}

.dd-retry:hover {
  text-decoration: underline;
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
