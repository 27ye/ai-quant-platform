<script setup lang="ts">
// V2 历史页路由占位：路由与入口先行锁定（V2 计划第 5 节），M2 由独立视图替换（A3/A4）
import { useRouter } from 'vue-router'

defineProps<{ title: string; plannedApi: string }>()

const router = useRouter()
</script>

<template>
  <main class="history-placeholder">
    <el-card shadow="never" class="card">
      <h1 class="title">{{ title }}</h1>
      <p class="desc">页面建设中，将接入 {{ plannedApi }}</p>
      <p class="hint">只读 GET：重看历史不触发重新计算或 LLM 生成</p>
      <el-button class="back" @click="router.back()">返回</el-button>
    </el-card>
  </main>
</template>

<style scoped>
.history-placeholder {
  width: 100%;
  box-sizing: border-box;
  padding: 16px 24px 48px;
}

.card {
  max-width: 560px;
  margin: 64px auto 0;
  background: var(--surface, #14171d);
  border: 1px solid var(--border, rgba(255, 255, 255, 0.06));
  border-radius: 8px;
  text-align: center;
}

.title {
  font-size: 18px;
  font-weight: 700;
  color: var(--text-main, rgba(255, 255, 255, 0.92));
  margin: 0 0 10px;
}

.desc {
  font-size: 13px;
  color: var(--text-sub, rgba(255, 255, 255, 0.62));
  margin: 0 0 6px;
}

.hint {
  font-size: 12px;
  color: var(--text-faint, rgba(255, 255, 255, 0.38));
  margin: 0 0 18px;
}
</style>
