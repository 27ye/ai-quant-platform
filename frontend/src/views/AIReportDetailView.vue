<script setup lang="ts">
// A4：AI 报告历史详情（/ai/reports/:id）
// 只读 GET /ai/reports/{id}，重放保存时的正文与快照元数据，绝不触发生成
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { AxiosError } from 'axios'

import { fetchAIReportDetail } from '../api/ai'
import type { AIReportDetail } from '../types/api'
import AIReportBody from '../components/ai/AIReportBody.vue'
import { formatDateTime, SOURCE_MODE_LABEL } from '../utils/format'

const route = useRoute()
const router = useRouter()
const reportId = computed(() => Number(route.params.id))

const report = ref<AIReportDetail | null>(null)
const loading = ref(true)
const failed = ref(false)
const notFound = ref(false)

const isLegacy = computed(() => report.value?.snapshot_status === 'legacy_missing')

// context_hash 64 位 hex 太长，展示头尾各 8 位
const shortHash = computed(() => {
  const hash = report.value?.context_hash
  if (!hash) return null
  return `${hash.slice(0, 8)}…${hash.slice(-8)}`
})

// C 在 Issue #11 指出：data_as_of 是上下文组装时间，不能当作行情截至日；
// 真正的行情截至取快照 provenance.market_end_date（legacy 报告无快照则不显示）
const marketEndDate = computed(
  () => report.value?.context_snapshot?.provenance.market_end_date ?? null,
)

// 过期请求防护（同 StockDetailView 的 epoch 模式）：
// 连续切换报告时，只有当前 epoch 的请求允许更新状态——成功、失败、finally 都拦，
// 避免慢的旧响应覆盖新正文、或旧请求的 finally 提前关闭新请求的 loading
const epoch = ref(0)

async function load() {
  const currentEpoch = ++epoch.value
  if (!Number.isInteger(reportId.value) || reportId.value <= 0) {
    loading.value = false
    notFound.value = true
    return
  }
  loading.value = true
  failed.value = false
  notFound.value = false
  report.value = null
  try {
    const res = await fetchAIReportDetail(reportId.value)
    if (epoch.value !== currentEpoch) return
    report.value = res.data
  } catch (error) {
    if (epoch.value !== currentEpoch) return
    // 契约：未知 ID 返回 HTTP 404 + code=40006（report not found；回测不存在是 40005）
    if (error instanceof AxiosError && error.response?.status === 404) {
      notFound.value = true
    } else {
      failed.value = true
    }
  } finally {
    if (epoch.value === currentEpoch) loading.value = false
  }
}

watch(reportId, load, { immediate: true })
</script>

<template>
  <main class="detail-page">
    <header class="page-header">
      <div class="header-left">
        <h1 class="page-title">AI 报告详情</h1>
        <span class="id-chip">#{{ reportId }}</span>
      </div>
    </header>

    <!-- 加载态 -->
    <el-card v-if="loading" shadow="never" class="panel">
      <el-skeleton :rows="8" animated />
    </el-card>

    <!-- 404 -->
    <el-card v-else-if="notFound" shadow="never" class="panel">
      <el-result icon="warning" title="报告不存在" sub-title="该报告可能已被删除，或链接有误">
        <template #extra>
          <el-button type="primary" @click="router.back()">返回</el-button>
        </template>
      </el-result>
    </el-card>

    <!-- 失败态 -->
    <el-card v-else-if="failed" shadow="never" class="panel">
      <el-result icon="error" title="加载失败" sub-title="报告获取失败，请稍后重试">
        <template #extra>
          <el-button type="primary" @click="load">重试</el-button>
        </template>
      </el-result>
    </el-card>

    <template v-else-if="report">
      <!-- 历史标记横幅 -->
      <div class="history-banner">
        <span class="banner-text">
          历史报告 · 生成于 {{ formatDateTime(report.created_at) }}
          <template v-if="marketEndDate"> · 行情截至 {{ marketEndDate }}</template>
        </span>
        <span class="mode-chip">{{ SOURCE_MODE_LABEL[report.source_mode] }}</span>
      </div>

      <!-- V1 旧报告：无快照，不用当前行情补写 -->
      <div v-if="isLegacy" class="legacy-notice">
        早期报告，无上下文快照与数据来源记录
      </div>

      <el-card shadow="never" class="panel report-panel">
        <AIReportBody :data="report" />
      </el-card>

      <!-- 快照元数据（完整快照时展示） -->
      <el-card v-if="!isLegacy && report.context_snapshot" shadow="never" class="panel meta-panel">
        <h3 class="meta-title">生成上下文</h3>
        <dl class="meta-grid">
          <div class="meta-item">
            <dt>数据来源</dt>
            <dd>
              {{ report.context_snapshot.provenance.provider }} ·
              {{ report.context_snapshot.provenance.market_start_date }} ~
              {{ report.context_snapshot.provenance.market_end_date }}（{{
                report.context_snapshot.provenance.market_rows
              }}
              行）
            </dd>
          </div>
          <div class="meta-item">
            <dt>新闻</dt>
            <dd>
              {{
                report.context_snapshot.provenance.news_status === 'available'
                  ? `${report.context_snapshot.provenance.news_count} 条`
                  : '当时无新闻'
              }}
            </dd>
          </div>
          <div class="meta-item">
            <dt>版本</dt>
            <dd>
              prompt {{ report.prompt_version }} · context
              {{ report.context_schema_version }} · output {{ report.output_schema_version }}
            </dd>
          </div>
          <div v-if="shortHash" class="meta-item">
            <dt>上下文哈希</dt>
            <dd class="hash">{{ shortHash }}</dd>
          </div>
        </dl>
      </el-card>

      <p class="regenerate-hint">
        需要最新分析？<router-link class="hint-link" :to="`/stock/${report.stock_code}`">
          回工作台重新生成
        </router-link>
      </p>
    </template>
  </main>
</template>

<style scoped>
.detail-page {
  width: 100%;
  max-width: 880px;
  margin: 0 auto;
  box-sizing: border-box;
  padding: 16px 24px 48px;
}

.page-header {
  padding-bottom: 14px;
  margin-bottom: 14px;
  border-bottom: 1px solid var(--border);
}

.header-left {
  display: flex;
  align-items: baseline;
  gap: 12px;
}

.page-title {
  margin: 0;
  font-size: 18px;
  font-weight: 700;
  color: var(--text-main);
}

.id-chip {
  font-size: 12px;
  color: var(--text-faint);
  font-variant-numeric: tabular-nums;
}

.panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
}

/* 历史标记横幅 */
.history-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 14px;
  margin-bottom: 12px;
  border: 1px solid var(--accent);
  border-radius: 8px;
  background: var(--accent-bg);
}

.banner-text {
  font-size: 12px;
  color: var(--accent);
  font-variant-numeric: tabular-nums;
}

.mode-chip {
  padding: 1px 8px;
  border: 1px solid var(--accent);
  border-radius: 999px;
  font-size: 10px;
  color: var(--accent);
  white-space: nowrap;
}

.legacy-notice {
  padding: 10px 14px;
  margin-bottom: 12px;
  border: 1px solid var(--border-strong);
  border-radius: 8px;
  font-size: 12px;
  color: var(--text-faint);
  text-align: center;
}

.report-panel {
  margin-bottom: 12px;
}

/* 快照元数据 */
.meta-panel {
  margin-bottom: 12px;
}

.meta-title {
  margin: 0 0 10px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-faint);
  letter-spacing: 0.04em;
}

.meta-grid {
  margin: 0;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px 16px;
}

.meta-item dt {
  font-size: 11px;
  color: var(--text-faint);
  margin-bottom: 2px;
}

.meta-item dd {
  margin: 0;
  font-size: 12px;
  color: var(--text-sub);
  font-variant-numeric: tabular-nums;
}

.hash {
  font-family: ui-monospace, monospace;
}

.regenerate-hint {
  margin: 4px 0 0;
  text-align: center;
  font-size: 12px;
  color: var(--text-faint);
}

.hint-link {
  color: var(--accent);
  text-decoration: none;
}

.hint-link:hover {
  text-decoration: underline;
}

@media (max-width: 760px) {
  .detail-page {
    padding: 12px 12px 32px;
  }

  .meta-grid {
    grid-template-columns: 1fr;
  }
}
</style>
