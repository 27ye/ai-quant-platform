<script setup lang="ts">
import { computed } from 'vue'

import type { NewsItem } from '../../types/api'

const props = defineProps<{ items: NewsItem[] }>()

const displayItems = computed(() => props.items)

// 后端返回 ISO 字符串，前端统一展示为 YYYY-MM-DD HH:mm
function formatTime(iso: string | null): string {
  if (!iso) return ''
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(
    date.getDate(),
  )} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}
</script>

<template>
  <el-card shadow="never" class="card-lift news-card">
    <template #header>
      <div class="header">
        <span>新闻资讯</span>
        <el-tag size="small" effect="plain" type="info">
          {{ displayItems.length }}
        </el-tag>
      </div>
    </template>

    <ul v-if="displayItems.length > 0" class="news-list">
      <li v-for="(item, idx) in displayItems" :key="idx" class="news-item">
        <a
          v-if="item.url"
          :href="item.url"
          target="_blank"
          rel="noopener noreferrer"
          class="title"
          >{{ item.title }}</a
        >
        <span v-else class="title static">{{ item.title }}</span>

        <div class="meta">
          <span v-if="item.source" class="source">{{ item.source }}</span>
          <span v-if="item.publish_time" class="time">{{
            formatTime(item.publish_time)
          }}</span>
        </div>

        <p v-if="item.summary" class="summary">{{ item.summary }}</p>
      </li>
    </ul>

    <el-empty v-else description="暂无新闻" :image-size="60" />
  </el-card>
</template>

<style scoped>
.header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
}

/* 列表内部滚动：避免长列表把卡片撑爆，与 AIReportCard 一致 */
.news-card :deep(.el-card__body) {
  max-height: 360px;
  overflow-y: auto;
  padding: 4px 12px 12px;
}

/* 暗色滚动条：6px 窄轨、半透明滑块 */
.news-card :deep(.el-card__body::-webkit-scrollbar) {
  width: 6px;
}
.news-card :deep(.el-card__body::-webkit-scrollbar-thumb) {
  background: rgba(255, 255, 255, 0.18);
  border-radius: 3px;
}
.news-card :deep(.el-card__body::-webkit-scrollbar-track) {
  background: transparent;
}

.news-list {
  margin: 0;
  padding: 0;
  list-style: none;
}

.news-item {
  padding: 12px 0;
  border-bottom: 1px solid var(--border, rgba(255, 255, 255, 0.07));
}
.news-item:last-child {
  border-bottom: none;
}

.title {
  display: block;
  color: rgba(255, 255, 255, 0.85);
  font-size: 14px;
  font-weight: 500;
  line-height: 1.5;
  text-decoration: none;
  transition: color 0.12s ease;
}
.title:hover {
  color: var(--accent, #d4a958);
}
.title.static {
  cursor: default;
}

.meta {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 4px;
  color: var(--text-faint, rgba(255, 255, 255, 0.38));
  font-size: 12px;
}
.time {
  font-variant-numeric: tabular-nums;
}

.summary {
  margin: 6px 0 0;
  color: var(--text-sub, rgba(255, 255, 255, 0.55));
  font-size: 13px;
  line-height: 1.6;
  /* 最多 2 行，溢出省略 */
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>
