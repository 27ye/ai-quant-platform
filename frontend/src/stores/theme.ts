// 主题（暗/亮）全局状态：localStorage 持久化，切换时同步 <html data-theme> 与 Element Plus 的 dark class
// 无 pinia，沿用 health store 的 reactive 模块模式
import { computed, reactive } from 'vue'

export type Theme = 'dark' | 'light'

const STORAGE_KEY = 'theme'

function initialTheme(): Theme {
  return localStorage.getItem(STORAGE_KEY) === 'light' ? 'light' : 'dark'
}

const state = reactive({
  theme: initialTheme() as Theme,
})

function apply(theme: Theme) {
  state.theme = theme
  localStorage.setItem(STORAGE_KEY, theme)
  const el = document.documentElement
  el.dataset.theme = theme
  el.classList.toggle('dark', theme === 'dark')
}

export function useThemeStore() {
  return reactive({
    theme: computed(() => state.theme),
    isDark: computed(() => state.theme === 'dark'),
    toggle: () => apply(state.theme === 'dark' ? 'light' : 'dark'),
  })
}
