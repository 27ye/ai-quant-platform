<script setup lang="ts">
import { computed } from 'vue'

import type { ScoreData } from '../../types/api'

const props = defineProps<{ data: ScoreData }>()

// 分项上限与 SPEC 一致：40 / 25 / 20 / 15
const ITEMS = [
  { key: 'trend_score', label: '趋势', max: 40 },
  { key: 'momentum_score', label: '动量', max: 25 },
  { key: 'volume_score', label: '量能', max: 20 },
  { key: 'risk_score', label: '风险', max: 15 },
] as const

const items = computed(() =>
  ITEMS.map((item) => {
    // 预热期分项为 null：显式展示「—」，不能当 0 分误导
    const raw = props.data[item.key]
    return {
      ...item,
      raw,
      display: raw == null ? '—' : String(raw),
      percent: raw == null ? 0 : Math.round((raw / item.max) * 100),
    }
  }),
)

// 等级颜色：红强、金中性、绿弱、灰更弱（A 股语义），level 为 C 定义的中文等级
const LEVEL_RULES: Array<{ match: string; type: 'danger' | 'warning' | 'success' | 'info' }> = [
  { match: '偏强', type: 'danger' },
  { match: '中性', type: 'warning' },
  { match: '偏弱', type: 'success' },
  { match: '较弱', type: 'info' },
]

const levelType = computed(() => {
  const level = props.data.level ?? ''
  return LEVEL_RULES.find((rule) => level.includes(rule.match))?.type ?? 'info'
})
</script>

<template>
  <el-card shadow="never" class="card-lift">
    <template #header>
      <div class="header">
        <span>量化评分</span>
        <el-tag size="small" effect="plain" :type="levelType">{{ data.level }}</el-tag>
      </div>
    </template>

    <div class="score-row">
      <span class="score">{{ data.score }}</span>
      <span class="score-total">/ 100</span>
      <span class="stock-code">{{ data.stock_code }}</span>
    </div>

    <div class="bars">
      <div v-for="item in items" :key="item.key" class="bar-row">
        <span class="bar-label">{{ item.label }}</span>
        <el-progress
          :percentage="item.percent"
          color="var(--accent)"
          :stroke-width="6"
          class="bar"
          :class="{ 'bar-empty': item.raw == null }"
        />
        <span class="bar-value">{{ item.display }}/{{ item.max }}</span>
      </div>
    </div>

    <ul class="reasons">
      <li v-for="reason in data.reasons" :key="reason">{{ reason }}</li>
    </ul>
  </el-card>
</template>

<style scoped>
.header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
}

.score-row {
  display: flex;
  align-items: baseline;
  gap: 6px;
  margin-bottom: 14px;
}

.score {
  font-size: 40px;
  font-weight: 700;
  line-height: 1;
}

.score-total {
  color: var(--text-faint);
  font-size: 13px;
}

.stock-code {
  margin-left: auto;
  color: var(--text-faint);
  font-size: 12px;
}

.bars {
  display: grid;
  gap: 10px;
  margin-bottom: 14px;
}

.bar-row {
  display: grid;
  grid-template-columns: 40px 1fr 64px;
  gap: 10px;
  align-items: center;
}

.bar-label {
  color: var(--text-sub);
  font-size: 13px;
}

.bar-value {
  color: var(--text-faint);
  font-size: 12px;
  text-align: right;
}

/* 预热期无分项：进度条淡化为底槽，不暗示 0 分 */
.bar-empty :deep(.el-progress-bar__inner) {
  background: var(--border-strong);
}

.reasons {
  margin: 0;
  padding: 12px 0 0;
  border-top: 1px solid var(--border);
  list-style: none;
}

.reasons li {
  position: relative;
  padding: 4px 0 4px 14px;
  color: var(--text-sub);
  font-size: 13px;
  line-height: 1.6;
}

.reasons li::before {
  content: '';
  position: absolute;
  left: 0;
  top: 12px;
  width: 5px;
  height: 5px;
  background: var(--text-faint);
  border-radius: 50%;
}
</style>
