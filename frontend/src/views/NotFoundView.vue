<script setup lang="ts">
// 404：非法路径给明确反馈（原实现静默重定向首页，用户无感知）
import { useRouter } from 'vue-router'

const router = useRouter()

function goBack() {
  // 新标签直接打开时没有历史记录，回退会退出站点；这种情况回首页
  if (window.history.length > 1) router.back()
  else router.replace('/')
}
</script>

<template>
  <main class="not-found">
    <el-result icon="warning" title="页面不存在" sub-title="地址可能已变更或输入有误">
      <template #extra>
        <el-button type="primary" @click="router.push('/')">回到工作台</el-button>
        <el-button @click="goBack">返回上一页</el-button>
      </template>
    </el-result>
  </main>
</template>

<style scoped>
.not-found {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 60vh;
  padding: 24px;
}
</style>
