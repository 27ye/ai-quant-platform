<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'

import { analyzeStock } from '../../api/ai'
import type { AIAnalysisData } from '../../types/api'
import AIReportBody from './AIReportBody.vue'

// 后端 AI 请求超时 120s（api/ai.ts），文案需与之保持一致
const TIMEOUT_SECONDS = 120

const props = defineProps<{ stockCode: string }>()

const report = ref<AIAnalysisData | null>(null)
const loading = ref(false)
const failed = ref(false)
const elapsedSeconds = ref(0)
let elapsedTimer: ReturnType<typeof setInterval> | null = null

// Epoch 机制：切换股票时递增，使在途的 AI 请求过期被丢弃
const epoch = ref(0)

function stopElapsedTimer() {
  if (elapsedTimer) {
    clearInterval(elapsedTimer)
    elapsedTimer = null
  }
}

async function run() {
  const currentEpoch = ++epoch.value
  loading.value = true
  failed.value = false
  report.value = null
  elapsedSeconds.value = 0
  stopElapsedTimer()
  elapsedTimer = setInterval(() => {
    if (epoch.value === currentEpoch) elapsedSeconds.value += 1
  }, 1000)
  try {
    const res = await analyzeStock(props.stockCode)
    if (epoch.value !== currentEpoch) return
    report.value = res.data
  } catch {
    if (epoch.value !== currentEpoch) return
    failed.value = true
  } finally {
    if (epoch.value === currentEpoch) {
      loading.value = false
      stopElapsedTimer()
    }
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

onBeforeUnmount(stopElapsedTimer)
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
        基于真实行情、技术指标、量化评分与新闻数据，由大模型生成综合投研分析。过程通常在
        {{ TIMEOUT_SECONDS }} 秒内完成，超时可手动重试。
      </p>
      <!-- 圆形渐变 CTA：参照 stock-dashboard 尾盘选股的开始分析按钮（渐变圆盘 + 闪电图标 + 双层光晕） -->
      <button type="button" class="analyze-orb" @click="run">
        <svg viewBox="0 0 24 24" width="28" height="28" fill="currentColor" aria-hidden="true">
          <path d="M13 2 4.5 13.5h5L8.5 22l8.5-11.5h-5L13 2z" />
        </svg>
        <span>开始 AI 分析</span>
      </button>
    </div>

    <!-- 加载态 -->
    <div v-else-if="loading" aria-live="polite">
      <el-skeleton :rows="6" animated />
      <p class="loading-hint">
        大模型正在读取数据并生成分析，已等待 {{ elapsedSeconds }}s（上限 {{ TIMEOUT_SECONDS }}s）…
      </p>
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
  margin-bottom: 20px;
}

/* 圆形主 CTA：主题色渐变圆盘，hover 放大 + 光晕加深，全程跟随 --accent */
.analyze-orb {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 172px;
  height: 172px;
  margin: 4px auto 12px;
  border: none;
  border-radius: 50%;
  background: linear-gradient(135deg, var(--accent) 0%, var(--accent-hover) 100%);
  color: #fff;
  font-size: 15px;
  font-weight: 600;
  font-family: inherit;
  cursor: pointer;
  box-shadow:
    0 8px 32px color-mix(in srgb, var(--accent) 32%, transparent),
    0 0 0 4px color-mix(in srgb, var(--accent) 12%, transparent);
  transition:
    transform 0.2s ease,
    box-shadow 0.2s ease;
}

.analyze-orb:hover {
  transform: scale(1.035);
  box-shadow:
    0 12px 44px color-mix(in srgb, var(--accent) 42%, transparent),
    0 0 0 6px color-mix(in srgb, var(--accent) 16%, transparent);
}

.analyze-orb:active {
  transform: scale(0.99);
}

.loading-hint {
  margin: 16px 0 0;
  color: var(--text-sub);
  font-size: 13px;
}
</style>
