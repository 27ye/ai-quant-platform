<script setup lang="ts">
// 暗/亮主题切换按钮
import { useThemeStore } from '../../stores/theme'

const theme = useThemeStore()
</script>

<template>
  <button
    type="button"
    class="theme-toggle"
    :title="theme.isDark ? '切换为浅色' : '切换为暗色'"
    :aria-label="theme.isDark ? '切换为浅色' : '切换为暗色'"
    @click="theme.toggle()"
  >
    <!-- 暗色时显示太阳（点此变亮），亮色时显示月亮 -->
    <svg v-if="theme.isDark" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </svg>
    <svg v-else viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8z" />
    </svg>
  </button>
</template>

<style scoped>
.theme-toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: transparent;
  color: var(--text-sub);
  cursor: pointer;
  transition:
    color 0.15s ease,
    border-color 0.15s ease,
    background 0.15s ease;
}

.theme-toggle:hover {
  color: var(--text-main);
  border-color: var(--border-strong);
  background: var(--surface-hover);
}
</style>
