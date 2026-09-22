<script setup lang="ts">
// A3：回测历史列表（/stock/:code/backtests）
// 只读 GET /backtests，排序 created_at DESC, id DESC；点击进详情重放保存时快照
// V3 F3：勾选两条记录进入对照页（同股票翻页保留 ≤2 个已选；切股票清空）
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

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

// V3 F3 对照选择：只存列表拿到的 ID（跨页保留；不预取详情）
const selectedIds = ref<number[]>([])

function toggleSelect(item: BacktestSummary) {
  const index = selectedIds.value.indexOf(item.backtest_id)
  if (index !== -1) {
    selectedIds.value.splice(index, 1)
    return
  }
  if (selectedIds.value.length >= 2) {
    ElMessage.warning('最多同时选择两条回测进行对照')
    return
  }
  selectedIds.value.push(item.backtest_id)
}

function cancelSelected(id: number) {
  const index = selectedIds.value.indexOf(id)
  if (index !== -1) selectedIds.value.splice(index, 1)
}

function goCompare() {
  if (selectedIds.value.length !== 2) return
  const [a, b] = selectedIds.value
  router.push({ path: '/backtests/compare', query: { a: String(a), b: String(b) } })
}

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

// 切股时回到第一页重新加载并清空对照选择（路由参数变化）
watch(
  stockCode,
  () => {
    page.value = 1
    selectedIds.value = []
    load()
  },
  { immediate: true },
)
</script>

<template>
  <main class="history-page">
    <header class="page-header">
      <div class="header-left">
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
      <p class="compare-hint">勾选两条记录可进行对照</p>
      <ul class="bt-list">
        <li
          v-for="item in items"
          :key="item.backtest_id"
          class="bt-item"
          :class="{ selected: selectedIds.includes(item.backtest_id) }"
          role="link"
          tabindex="0"
          :aria-label="`打开回测 ${item.backtest_id} 详情`"
          @click="openDetail(item.backtest_id)"
          @keydown.enter.prevent="openDetail(item.backtest_id)"
        >
          <el-checkbox
            :model-value="selectedIds.includes(item.backtest_id)"
            class="select-box"
            :aria-label="`选择回测 ${item.backtest_id} 进行对照`"
            @click.stop
            @change="toggleSelect(item)"
          />
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

      <!-- V3 F3 选择条：显示代码与 ID，可取消；选中两条后进入对照 -->
      <div v-if="selectedIds.length > 0" class="select-bar">
        <span class="select-label">已选 {{ stockCode }}</span>
        <span v-for="id in selectedIds" :key="id" class="select-chip">
          #{{ id }}
          <button type="button" class="chip-x" :aria-label="`取消选择 ${id}`" @click="cancelSelected(id)">
            ×
          </button>
        </span>
        <el-button
          type="primary"
          size="small"
          class="compare-btn"
          :disabled="selectedIds.length !== 2"
          @click="goCompare"
        >
          开始对照（{{ selectedIds.length }}/2）
        </el-button>
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

/* V3 F3：已选记录高亮 */
.bt-item.selected {
  border-color: var(--accent);
  background: var(--accent-bg);
}

.compare-hint {
  margin: 0 0 10px;
  color: var(--text-faint);
  font-size: 12px;
}

.select-box {
  height: auto;
  margin-right: 4px;
}

/* V3 F3 选择条：贴底吸顶展示已选 ID */
.select-bar {
  position: sticky;
  bottom: 12px;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 16px;
  padding: 10px 14px;
  border: 1px solid var(--accent);
  border-radius: 8px;
  background: var(--surface);
  box-shadow: var(--shadow-md);
}

.select-label {
  color: var(--text-main);
  font-size: 12px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.select-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border: 1px solid var(--accent);
  border-radius: 999px;
  color: var(--accent);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.chip-x {
  padding: 0;
  border: none;
  background: none;
  color: inherit;
  font-size: 13px;
  line-height: 1;
  cursor: pointer;
  opacity: 0.7;
}

.chip-x:hover {
  opacity: 1;
}

.compare-btn {
  margin-left: auto;
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
