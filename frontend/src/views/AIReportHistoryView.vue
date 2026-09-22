<script setup lang="ts">
// A4：AI 报告历史列表（/stock/:code/ai-reports）
// 只读 GET /ai/reports，按 created_at DESC, id DESC 排序；重看不触发 LLM 生成
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { fetchAIReports } from '../api/ai'
import type { AIReportSummary, TrendValue } from '../types/api'
import { formatDateTime, SOURCE_MODE_LABEL, TREND_LABEL } from '../utils/format'

const route = useRoute()
const router = useRouter()
const stockCode = computed(() => String(route.params.code ?? ''))

const items = ref<AIReportSummary[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const loading = ref(true)
const failed = ref(false)

function trendClass(trend: TrendValue): string {
  if (trend === 'bullish') return 'up'
  if (trend === 'bearish') return 'down'
  return ''
}

// 过期请求防护（同 StockDetailView 的 epoch 模式）：
// 快速翻页/切股时，只有当前 epoch 的请求允许更新状态
const epoch = ref(0)

async function load() {
  const currentEpoch = ++epoch.value
  loading.value = true
  failed.value = false
  try {
    const res = await fetchAIReports({
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

function openDetail(reportId: number) {
  router.push(`/ai/reports/${reportId}`)
}

function onPageChange(next: number) {
  page.value = next
  load()
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
        <h1 class="page-title">AI 报告历史</h1>
        <span class="stock-chip">{{ stockCode }}</span>
      </div>
      <span v-if="!loading && !failed" class="total">共 {{ total }} 份</span>
    </header>

    <!-- 加载态 -->
    <el-card v-if="loading" shadow="never" class="panel">
      <el-skeleton :rows="5" animated />
    </el-card>

    <!-- 失败态 -->
    <el-card v-else-if="failed" shadow="never" class="panel">
      <el-result icon="error" title="加载失败" sub-title="报告列表获取失败，请稍后重试">
        <template #extra>
          <el-button type="primary" @click="load">重试</el-button>
        </template>
      </el-result>
    </el-card>

    <!-- 空态 -->
    <el-card v-else-if="items.length === 0" shadow="never" class="panel">
      <el-empty description="暂无报告，回工作台生成第一份 AI 分析" />
    </el-card>

    <!-- 列表 -->
    <template v-else>
      <ul class="report-list">
        <li
          v-for="(item, index) in items"
          :key="item.report_id"
          class="report-item"
          role="link"
          tabindex="0"
          :aria-label="`打开 AI 报告 ${item.report_id}`"
          @click="openDetail(item.report_id)"
          @keydown.enter.prevent="openDetail(item.report_id)"
        >
          <div class="item-main">
            <div class="item-top">
              <span :class="['trend', trendClass(item.trend)]">
                {{ item.analysis_mode === 'custom_backtest' ? '回测解读' : TREND_LABEL[item.trend] }}
              </span>
              <span v-if="item.analysis_mode === 'standard'" class="score">
                评分 {{ item.quant_score ?? '—' }}
              </span>
              <span v-else class="score">回测 #{{ item.backtest_id }}</span>
              <span v-if="page === 1 && index === 0" class="tag tag-latest">最新</span>
              <span
                v-if="item.snapshot_status === 'legacy_missing'"
                class="tag tag-legacy"
              >
                早期报告
              </span>
            </div>
            <p class="summary">{{ item.summary }}</p>
            <div class="item-meta">
              <span>{{ formatDateTime(item.created_at) }}</span>
              <span>{{ item.model_name }}</span>
              <span>{{ SOURCE_MODE_LABEL[item.source_mode] }}</span>
              <!-- data_as_of 是上下文组装时间（C 于 Issue #11 指出），口径待 D 确认后再展示 -->
            </div>
          </div>
          <span class="arrow" aria-hidden="true">›</span>
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

.page-title {
  margin: 0;
  font-size: 18px;
  font-weight: 700;
  color: var(--text-main);
}

.stock-chip {
  font-size: 12px;
  color: var(--text-faint);
  font-variant-numeric: tabular-nums;
}

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

.report-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.report-item {
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

.report-item:hover {
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
  margin-bottom: 6px;
}

.trend {
  font-size: 13px;
  font-weight: 700;
}

.trend.up {
  color: var(--up);
}

.trend.down {
  color: var(--down);
}

.score {
  font-size: 12px;
  color: var(--text-sub);
  font-variant-numeric: tabular-nums;
}

.tag {
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 10px;
  letter-spacing: 0.04em;
}

.tag-latest {
  border: 1px solid var(--accent);
  background: var(--accent-bg);
  color: var(--accent);
}

.tag-legacy {
  border: 1px solid var(--border-strong);
  color: var(--text-faint);
}

.summary {
  margin: 0 0 8px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-sub);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.item-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 14px;
  font-size: 11px;
  color: var(--text-faint);
  font-variant-numeric: tabular-nums;
}

.arrow {
  color: var(--text-faint);
  font-size: 18px;
  flex-shrink: 0;
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

  .page-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
  }
}
</style>
