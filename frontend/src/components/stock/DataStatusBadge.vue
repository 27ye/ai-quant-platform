<script setup lang="ts">
// V2 A1：数据状态徽标（替换 V1 写死的「冻结演示」文案）
// 映射规则来自 B 在 Issue #11 的建议：
//   mode=unknown → 灰「无来源元数据」
//   fresh → 绿「数据截至 X」
//   stale → 黄「数据截至 X（N 天前），可能非最新」
//   freshness=unknown 或 rows=0 → 灰「暂无行情数据」
// coverage=unknown 时不得显示「完整/已覆盖」（本组件不展示覆盖文案）
import { computed } from 'vue'

import type { DataStatus } from '../../types/api'

const props = defineProps<{ status: DataStatus }>()

const badge = computed<{ text: string; tone: 'green' | 'yellow' | 'gray' }>(() => {
  const k = props.status.kline
  if (k.mode === 'unknown') return { text: '无来源元数据', tone: 'gray' }
  if (k.rows === 0 || k.freshness.status === 'unknown') {
    return { text: '暂无行情数据', tone: 'gray' }
  }
  const end = k.last_trade_date ?? '—'
  if (k.freshness.status === 'stale') {
    const days = k.freshness.stale_days
    return {
      text:
        days != null
          ? `数据截至 ${end}（${days} 天前），可能非最新`
          : `数据截至 ${end}，可能非最新`,
      tone: 'yellow',
    }
  }
  return { text: `数据截至 ${end}`, tone: 'green' }
})
</script>

<template>
  <span class="data-badge" :class="badge.tone">{{ badge.text }}</span>
</template>

<style scoped>
.data-badge {
  padding: 2px 10px;
  border: 1px solid;
  border-radius: 999px;
  font-size: 11px;
  letter-spacing: 0.04em;
  white-space: nowrap;
}

.green {
  color: var(--down);
  border-color: var(--down);
  background: var(--down-bg);
}

.yellow {
  color: var(--warn);
  border-color: var(--warn);
  background: var(--warn-bg);
}

.gray {
  color: var(--text-faint);
  border-color: var(--border-strong);
  background: var(--surface-hover);
}
</style>
