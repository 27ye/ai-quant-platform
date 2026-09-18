<script setup lang="ts">
// A3：回测历史列表（/stock/:code/backtests）
// 只读 GET /backtests，排序 created_at DESC, id DESC；点击进详情重放保存时快照
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { fetchBacktests } from '../api/backtests'
import type { BacktestSummary } from '../types/api'
import { formatDateTime } from '../utils/format'

const route = useRoute()
const router = useRouter()
const stockCode = computed(() => String(route.params.code ?? ''))

const items = ref<BacktestSummary[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const loading = ref(true)
const failed = ref(false)

// 过期请求防护（同 StockDetailView 的 epoch 模式，C 复核要求）
const epoch = ref(0)

async function load() {
  const currentEpoch = ++epoch.value
  loading.value = true
  failed.value = false
  try {
    const res = await fetchBacktests({
      stock_code: stockCode.value,
      page: page.value,
      page_size: pageSize,
    })
    if (epoch.value !== currentEpoch) return
    items.value = res.data.items
    total.value = res.data.total
  } catch {
    if (epoch.value !== currentEpoch) return
    failed.value = true
  } finally {
    if (epoch.value === currentEpoch) loading.value = false
  }
}

function openDetail(backtestId: number) {
  router.push(`/backtests/${backtestId}`)
}

function onPageChange(next: number) {
  page.value = next
  load()
}

function formatReturn(value: number | null): string {
  if (value == null) return '—'
  const sign = value > 0 ? '+' : ''
  return `${sign}${(value * 100).toFixed(2)}%`
}

function returnClass(value: number | null): string {
  if (value == null) return ''
  if (value > 0) return 'up'
  if (value < 0) return 'down'
  return ''
}

// 切股时回到第一页重新加载（路由参数变化）
watch(
  stockCode,
  () => {
    page.value = 1
    load()
  },
  { immediate: true },
)
</script>

<template>
  <main class="history-page">
    <header class="page-header">
      <div class="header-left">
        <router-link class="back-link" :to="`/stock/${stockCode}`">← 返回工作台</router-link>
        <h1 class="page-title">回测历史</h1>
        <span class="stock-chip">{{ stockCode }}</span>
      </div>
      <span v-if="!loading && !failed" class="total">共 {{ total }} 条</span>
    </header>

    <!-- 加载态 -->
    <el-card v-if="loading" shadow="never" class="panel">
      <el-skeleton :rows="5" animated />
    </el-card>

    <!-- 失败态 -->
    <el-card v-else-if="failed" shadow="never" class="panel">
      <el-result icon="error" title="加载失败" sub-title="回测列表获取失败，请稍后重试">
        <template #extra>
          <el-button type="primary" @click="load">重试</el-button>
        </template>
      </el-result>
    </el-card>

    <!-- 空态 -->
    <el-card v-else-if="items.length === 0" shadow="never" class="panel">
      <el-empty description="暂无回测记录，回工作台跑一次回测" />
    </el-card>

    <!-- 列表 -->
    <template v-else>
      <ul class="bt-list">
        <li
          v-for="item in items"
          :key="item.backtest_id"
          class="bt-item"
          @click="openDetail(item.backtest_id)"
        >
          <div class="item-main">
            <div class="item-top">
              <span class="bt-id">#{{ item.backtest_id }}</span>
              <span
                class="tag"
                :class="item.semantics_version === 'v2_windowed' ? 'tag-v2' : 'tag-v1'"
              >
                {{ item.semantics_version === 'v2_windowed' ? '参数化' : 'V1 快速' }}
              </span>
              <span v-if="item.snapshot_status === 'missing'" class="tag tag-missing">
                快照缺失
              </span>
            </div>
            <div class="item-range">{{ item.start_date }} ~ {{ item.end_date }}</div>
            <div class="item-meta">
              <span>{{ item.strategy_name }}</span>
              <span>往返 {{ item.trade_count }} 次</span>
              <span>成交 {{ item.order_count }} 笔</span>
              <span>{{ formatDateTime(item.created_at) }}</span>
            </div>
          </div>
          <div class="item-right">
            <span :class="['return', returnClass(item.total_return)]">
              {{ formatReturn(item.total_return) }}
            </span>
            <span class="arrow" aria-hidden="true">›</span>
          </div>
        </li>
      </ul>

      <div v-if="total > pageSize" class="pagination">
        <el-pagination
          layout="prev, pager, next"
          :total="total"
          :page-size="pageSize"
          :current-page="page"
          @current-change="onPageChange"
        />
      </div>
    </template>
  </main>
</template>

<style scoped>
.history-page {
  width: 100%;
  max-width: 880px;
  margin: 0 auto;
  box-sizing: border-box;
  padding: 16px 24px 48px;
}

.page-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  padding-bottom: 14px;
  margin-bottom: 14px;
  border-bottom: 1px solid var(--border);
}

.header-left {
  display: flex;
  align-items: baseline;
  gap: 12px;
  min-width: 0;
}

.back-link {
  color: var(--text-faint);
  font-size: 12px;
  text-decoration: none;
  white-space: nowrap;
  transition: color 0.15s ease;
}

.back-link:hover {
  color: var(--accent);
}

.page-title {
  margin: 0;
  font-size: 18px;
  font-weight: 700;
  color: var(--text-main);
}

.stock-chip,
.total {
  font-size: 12px;
  color: var(--text-faint);
  font-variant-numeric: tabular-nums;
}

.panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
}

.bt-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.bt-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  cursor: pointer;
  transition:
    border-color 0.15s ease,
    background 0.15s ease;
}

.bt-item:hover {
  background: var(--surface-hover);
  border-color: var(--border-strong);
}

.item-main {
  flex: 1;
  min-width: 0;
}

.item-top {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 4px;
}

.bt-id {
  font-size: 13px;
  font-weight: 700;
  color: var(--text-main);
  font-variant-numeric: tabular-nums;
}

.tag {
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 10px;
  letter-spacing: 0.04em;
}

.tag-v2 {
  border: 1px solid var(--accent);
  background: var(--accent-bg);
  color: var(--accent);
}

.tag-v1,
.tag-missing {
  border: 1px solid var(--border-strong);
  color: var(--text-faint);
}

.item-range {
  font-size: 13px;
  color: var(--text-sub);
  font-variant-numeric: tabular-nums;
  margin-bottom: 6px;
}

.item-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 14px;
  font-size: 11px;
  color: var(--text-faint);
  font-variant-numeric: tabular-nums;
}

.item-right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.return {
  font-size: 16px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.return.up {
  color: var(--up);
}

.return.down {
  color: var(--down);
}

.arrow {
  color: var(--text-faint);
  font-size: 18px;
}

.pagination {
  display: flex;
  justify-content: center;
  margin-top: 18px;
}

@media (max-width: 760px) {
  .history-page {
    padding: 12px 12px 32px;
  }
}
</style>
