<script setup lang="ts">
import { ref, watch } from 'vue'

import { analyzeStock } from '../../api/ai'
import type { AIAnalysisData } from '../../types/api'
import AIReportBody from './AIReportBody.vue'

const props = defineProps<{ stockCode: string }>()

const report = ref<AIAnalysisData | null>(null)
const loading = ref(false)
const failed = ref(false)

// Epoch 机制：切换股票时递增，使在途的 AI 请求过期被丢弃
const epoch = ref(0)

async function run() {
  const currentEpoch = ++epoch.value
  loading.value = true
  failed.value = false
  report.value = null
  try {
    const res = await analyzeStock(props.stockCode)
    if (epoch.value !== currentEpoch) return
    report.value = res.data
  } catch {
    if (epoch.value !== currentEpoch) return
    failed.value = true
  } finally {
    if (epoch.value === currentEpoch) loading.value = false
  }
}

// 切换股票时重置旧报告并使在途请求过期
watch(
  () => props.stockCode,
  () => {
    epoch.value++
    report.value = null
    failed.value = false
  },
)
</script>

<template>
  <el-card shadow="never" class="ai-card">
    <template #header>
      <div class="card-header">
        <span>AI 投研分析</span>
        <div class="header-actions">
          <router-link class="history-link" :to="`/stock/${stockCode}/ai-reports`">
            历史报告
          </router-link>
          <el-button
            v-if="report || failed"
            size="small"
            :disabled="loading"
            @click="run"
          >
            重新分析
          </el-button>
        </div>
      </div>
    </template>

    <!-- 初始态 -->
    <div v-if="!loading && !report && !failed" class="idle">
      <p>
        基于真实行情、技术指标、量化评分与新闻数据，由大模型生成综合投研分析。过程约需
        10~30 秒。
      </p>
      <el-button type="primary" @click="run">开始 AI 分析</el-button>
    </div>

    <!-- 加载态 -->
    <div v-else-if="loading">
      <el-skeleton :rows="6" animated />
      <p class="loading-hint">大模型正在读取数据并生成分析，请稍候…</p>
    </div>

    <!-- 失败态 -->
    <div v-else-if="failed">
      <el-result icon="error" title="分析失败" sub-title="请稍后重试，或检查后端 AI 服务状态">
        <template #extra>
          <el-button type="primary" @click="run">重试</el-button>
        </template>
      </el-result>
    </div>

    <!-- 报告正文（与历史详情页共用展示组件） -->
    <AIReportBody v-else-if="report" :data="report" />
  </el-card>
</template>

<style scoped>
.ai-card {
  margin-bottom: 16px;
  display: flex;
  flex-direction: column;
}

.ai-card :deep(.el-card__body) {
  flex: 1;
  min-height: 0;
  max-height: calc(100vh - 220px);
  overflow-y: auto;
}

.ai-card :deep(.el-card__body::-webkit-scrollbar) {
  width: 6px;
}

.ai-card :deep(.el-card__body::-webkit-scrollbar-track) {
  background: transparent;
}

.ai-card :deep(.el-card__body::-webkit-scrollbar-thumb) {
  background: var(--border-strong);
  border-radius: 3px;
}

.ai-card :deep(.el-card__body::-webkit-scrollbar-thumb:hover) {
  background: var(--text-faint);
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: 600;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.history-link {
  color: var(--text-faint);
  font-size: 12px;
  font-weight: 400;
  text-decoration: none;
  transition: color 0.15s ease;
}

.history-link:hover {
  color: var(--accent);
}

.idle p {
  color: var(--text-sub);
  margin-bottom: 16px;
}

.loading-hint {
  margin: 16px 0 0;
  color: var(--text-sub);
  font-size: 13px;
}
</style>
