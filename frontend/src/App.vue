<script setup lang="ts">
// 布局分流：首页全屏无壳（保留 K 线背景 hero），其余页面走侧栏 + 顶栏外壳
import { computed } from 'vue'
import { useRoute } from 'vue-router'

import AppShell from './components/layout/AppShell.vue'

const route = useRoute()
const isHome = computed(() => route.name === 'home')
</script>

<template>
  <router-view v-if="isHome" v-slot="{ Component }">
    <transition name="page" mode="out-in">
      <component :is="Component" />
    </transition>
  </router-view>

  <AppShell v-else>
    <router-view v-slot="{ Component }">
      <transition name="page" mode="out-in">
        <component :is="Component" />
      </transition>
    </router-view>
  </AppShell>
</template>
