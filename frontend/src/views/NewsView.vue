<script setup lang="ts">
// 新闻资讯独立页（/stock/:code/news）：从工作台拆出，整页展示，接口上限 50 条
// 侧栏可直达，页内不再放返回链接
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import { fetchNews } from '../api/news'
import type { NewsItem } from '../types/api'
import { formatDateTime } from '../utils/format'

const route = useRoute()
const stockCode = computed(() => String(route.params.code ?? ''))

const items = ref<NewsItem[]>([])
const loading = ref(true)
const failed = ref(false)

// 过期请求防护（同 StockDetailView 的 epoch 模式）
const epoch = ref(0)

async function load() {
  const currentEpoch = ++epoch.value
  loading.value = true
  failed.value = false
  try {
    const res = await fetchNews(stockCode.value, 50)
    if (epoch.value !== currentEpoch) return
    // mock 池条目有限会循环重复，按标题去重，保证演示列表干净
    const seen = new Set<string>()
    items.value = (res.data ?? []).filter((item) => {
      if (seen.has(item.title)) return false
      seen.add(item.title)
      return true
    })
  } catch {
    if (epoch.value !== currentEpoch) return
    failed.value = true
  } finally {
    if (epoch.value === currentEpoch) loading.value = false
  }
}

// 序号展示：补零两位（02、03…），头条不显示序号
function rank(idx: number): string {
  return String(idx + 1).padStart(2, '0')
}

// 切股时重新加载（路由参数变化）
watch(stockCode, load, { immediate: true })
</script>

<template>
  <main class="news-page">
    <header class="page-header">
      <div class="header-left">
        <h1 class="page-title">新闻资讯</h1>
        <span class="stock-chip">{{ stockCode }}</span>
      </div>
      <span v-if="!loading && !failed" class="total">共 {{ items.length }} 条</span>
    </header>

    <!-- 加载态 -->
    <el-card v-if="loading" shadow="never" class="panel">
      <el-skeleton :rows="5" animated />
    </el-card>

    <!-- 失败态 -->
    <el-card v-else-if="failed" shadow="never" class="panel">
      <el-result icon="error" title="加载失败" sub-title="新闻列表获取失败，请稍后重试">
        <template #extra>
          <el-button type="primary" @click="load">重试</el-button>
        </template>
      </el-result>
    </el-card>

    <!-- 空态 -->
    <el-card v-else-if="items.length === 0" shadow="never" class="panel">
      <el-empty description="暂无新闻" />
    </el-card>

    <!-- 列表：头条大字卡 + 序号条目，整卡可点，新标签打开原文 -->
    <ul v-else class="news-list">
      <li
        v-for="(item, idx) in items"
        :key="idx"
        class="news-li"
        :style="{ animationDelay: `${idx * 45}ms` }"
      >
        <component
          :is="item.url ? 'a' : 'div'"
          :class="['news-item', { featured: idx === 0 }]"
          v-bind="
            item.url
              ? { href: item.url, target: '_blank', rel: 'noopener noreferrer' }
              : {}
          "
        >
          <span v-if="idx > 0" class="item-rank">{{ rank(idx) }}</span>

          <div class="item-main">
            <div class="item-topline">
              <span v-if="idx === 0" class="tag-latest">最新</span>
              <span class="item-title">{{ item.title }}</span>
            </div>
            <p v-if="item.summary" class="item-summary">{{ item.summary }}</p>
            <div class="item-meta">
              <span v-if="item.source" class="item-source">{{ item.source }}</span>
              <span v-if="item.publish_time" class="item-time">{{
                formatDateTime(item.publish_time)
              }}</span>
            </div>
          </div>

          <svg
            v-if="item.url"
            class="item-arrow"
            viewBox="0 0 24 24"
            width="16"
            height="16"
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <path d="M7 17 17 7" />
            <path d="M8 7h9v9" />
          </svg>
        </component>
      </li>
    </ul>
  </main>
</template>

<style scoped>
.news-page {
  width: 100%;
  max-width: 880px;
  margin: 0 auto;
  box-sizing: border-box;
  padding: 20px 24px 48px;
}

.page-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  padding-bottom: 14px;
  margin-bottom: 16px;
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
  letter-spacing: 0.01em;
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

/* 条目渐入：按 index 交错 45ms，低调出现 */
.news-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.news-li {
  animation: news-in 0.35s ease both;
}

@keyframes news-in {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* 新闻条目：平面卡片 + 细边框，hover 微上浮 */
.news-item {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  padding: 14px 16px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: inherit;
  text-decoration: none;
  transition:
    border-color 0.15s ease,
    background 0.15s ease,
    transform 0.15s ease,
    box-shadow 0.15s ease;
}

a.news-item:hover {
  background: var(--surface-hover);
  border-color: var(--border-strong);
  transform: translateY(-1px);
  box-shadow: var(--shadow-sm);
}

/* 头条卡：更大留白 + 左上 accent 微光渐变，标题升一级 */
.news-item.featured {
  padding: 20px;
  background:
    linear-gradient(135deg, var(--accent-bg) 0%, transparent 45%),
    var(--surface);
}

.news-item.featured .item-title {
  font-size: 16px;
}

.news-item.featured .item-summary {
  -webkit-line-clamp: 3;
  line-clamp: 3;
}

/* 序号：等宽数字，低对比 */
.item-rank {
  flex-shrink: 0;
  width: 22px;
  padding-top: 3px;
  color: var(--text-faint);
  font-size: 12px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  opacity: 0.75;
}

.item-main {
  flex: 1;
  min-width: 0;
}

.item-topline {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

/* 「最新」小胶囊 */
.tag-latest {
  flex-shrink: 0;
  padding: 1px 7px;
  border-radius: 999px;
  background: var(--accent-bg);
  color: var(--accent);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.05em;
}

.item-title {
  font-size: 14px;
  font-weight: 600;
  line-height: 1.5;
  color: var(--text-main);
  transition: color 0.15s ease;
}

a.news-item:hover .item-title {
  color: var(--accent);
}

.item-summary {
  margin: 6px 0 0;
  color: var(--text-sub);
  font-size: 13px;
  line-height: 1.6;
  /* 默认最多 2 行，头条 3 行 */
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.item-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 8px;
  color: var(--text-faint);
  font-size: 12px;
}

/* 来源 chip */
.item-source {
  padding: 1px 7px;
  border: 1px solid var(--border-strong);
  border-radius: 4px;
  font-size: 11px;
}

.item-time {
  font-variant-numeric: tabular-nums;
}

/* 外链箭头：hover 时向右上微移并点亮 */
.item-arrow {
  flex-shrink: 0;
  margin-top: 2px;
  color: var(--text-faint);
  transition:
    color 0.15s ease,
    transform 0.15s ease;
}

a.news-item:hover .item-arrow {
  color: var(--accent);
  transform: translate(1px, -1px);
}

@media (max-width: 760px) {
  .news-page {
    padding: 12px 12px 32px;
  }

  .item-rank {
    display: none;
  }
}
</style>
