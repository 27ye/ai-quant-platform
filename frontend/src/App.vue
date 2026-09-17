<script setup lang="ts">
// 全站统一外壳：左侧栏 + 顶栏（原无壳首页已并入外壳，hero 见 /home 路由）
import AppShell from './components/layout/AppShell.vue'
</script>

<template>
  <AppShell>
    <router-view v-slot="{ Component }">
      <transition name="page" mode="out-in">
        <component :is="Component" />
      </transition>
    </router-view>
  </AppShell>
</template>
