<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'

import { searchStocks } from './api/stocks'
import type { StockBrief } from './types/api'
import { useHealthStore } from './stores/health'

const router = useRouter()
const health = useHealthStore()

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
  <div class="app-frame">
    <header class="top-bar">
      <router-link to="/" class="brand">
        <span class="brand-mark" aria-hidden="true"></span>
        <span class="brand-name">量化投研</span>
      </router-link>

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

      <div class="health-indicator">
        <span
          :class="['dot', health.status === 'ok' ? 'ok' : 'err']"
          :title="health.status === 'ok' ? '后端已连接' : '后端未连接'"
        ></span>
        <span v-if="health.acceptanceMode" class="mode-tag">{{ health.acceptanceMode }}</span>
      </div>
    </header>

    <router-view v-slot="{ Component }">
      <transition name="page" mode="out-in">
        <component :is="Component" />
      </transition>
    </router-view>
  </div>
</template>

<style scoped>
.app-frame {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.top-bar {
  position: sticky;
  top: 0;
  z-index: 100;
  display: flex;
  align-items: center;
  gap: 24px;
  height: 52px;
  padding: 0 24px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(14, 17, 22, 0.92);
  backdrop-filter: blur(12px);
}

.brand {
  display: flex;
  align-items: center;
  gap: 8px;
  text-decoration: none;
  flex-shrink: 0;
}

.brand-mark {
  width: 8px;
  height: 8px;
  border-radius: 1px;
  background: var(--accent, #d4a958);
}

.brand-name {
  color: rgba(255, 255, 255, 0.92);
  font-size: 14px;
  font-weight: 600;
  letter-spacing: 0.04em;
}

.search-wrapper {
  position: relative;
  flex: 1;
  max-width: 420px;
}

.search-input :deep(.el-input__wrapper) {
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 6px;
  box-shadow: none;
  height: 34px;
}

.search-input :deep(.el-input__wrapper:hover) {
  border-color: rgba(255, 255, 255, 0.12);
}

.search-input :deep(.el-input__wrapper.is-focus) {
  border-color: var(--accent, #d4a958);
  background: rgba(255, 255, 255, 0.06);
}

.search-input :deep(.el-input__inner) {
  color: rgba(255, 255, 255, 0.85);
  font-size: 13px;
}

.search-input :deep(.el-input__inner::placeholder) {
  color: rgba(255, 255, 255, 0.32);
}

.search-icon {
  color: rgba(255, 255, 255, 0.32);
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
  background: #181c23;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 6px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
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
  color: inherit;
  transition: background 0.12s ease;
}

.dropdown-item:hover {
  background: rgba(255, 255, 255, 0.06);
}

.dd-name {
  font-size: 13px;
  font-weight: 500;
}

.dd-code {
  color: rgba(255, 255, 255, 0.38);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.health-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}

.dot.ok {
  background: #00b386;
}

.dot.err {
  background: rgba(255, 255, 255, 0.2);
}

.mode-tag {
  padding: 1px 6px;
  border: 1px solid var(--accent, #d4a958);
  border-radius: 3px;
  color: var(--accent, #d4a958);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}

@media (max-width: 760px) {
  .top-bar {
    padding: 0 12px;
    gap: 12px;
  }

  .brand-name {
    display: none;
  }

  .search-wrapper {
    max-width: none;
  }
}
</style>
