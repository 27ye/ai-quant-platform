// 主题（暗/亮）+ 强调色全局状态：localStorage 持久化
// 暗亮切换同步 <html data-theme> 与 Element Plus 的 dark class；
// 强调色以 documentElement 行内 CSS 变量覆盖样式表默认值（含 Element Plus 主色一族，保证控件联动）
import { computed, reactive } from 'vue'

export type Theme = 'dark' | 'light'

export interface AccentOption {
  name: string
  hex: string
}

// 顶栏主题色面板的可选强调色（第一项为默认极简蓝，与样式表一致）
export const ACCENT_OPTIONS: AccentOption[] = [
  { name: '极简蓝', hex: '#3b82f6' },
  { name: '靛青', hex: '#6366f1' },
  { name: '紫罗兰', hex: '#8b5cf6' },
  { name: '品红', hex: '#ec4899' },
  { name: '暖橙', hex: '#f97316' },
  { name: '金黄', hex: '#eab308' },
  { name: '青', hex: '#06b6d4' },
  { name: '翠绿', hex: '#22c55e' },
]

const THEME_KEY = 'theme'
const ACCENT_KEY = 'accent'

function initialTheme(): Theme {
  return localStorage.getItem(THEME_KEY) === 'light' ? 'light' : 'dark'
}

function initialAccent(): string | null {
  const v = localStorage.getItem(ACCENT_KEY)
  return v && /^#[0-9a-fA-F]{6}$/.test(v) ? v : null
}

const state = reactive({
  theme: initialTheme() as Theme,
  accent: initialAccent() as string | null,
})

// hex 混色：weight 为 b 的占比（0~1）
function mixHex(a: string, b: string, weight: number): string {
  const pa = parseInt(a.slice(1), 16)
  const pb = parseInt(b.slice(1), 16)
  const r = Math.round(((pa >> 16) & 255) * (1 - weight) + ((pb >> 16) & 255) * weight)
  const g = Math.round(((pa >> 8) & 255) * (1 - weight) + ((pb >> 8) & 255) * weight)
  const bl = Math.round((pa & 255) * (1 - weight) + (pb & 255) * weight)
  return `#${((r << 16) | (g << 8) | bl).toString(16).padStart(6, '0')}`
}

function rgba(hex: string, alpha: number): string {
  const p = parseInt(hex.slice(1), 16)
  return `rgba(${(p >> 16) & 255}, ${(p >> 8) & 255}, ${p & 255}, ${alpha})`
}

// 自定义强调色需要覆盖的变量
const ACCENT_VARS = [
  '--accent',
  '--accent-hover',
  '--accent-bg',
  '--el-color-primary',
  '--el-color-primary-dark-2',
  '--el-color-primary-light-3',
  '--el-color-primary-light-5',
  '--el-color-primary-light-7',
  '--el-color-primary-light-8',
  '--el-color-primary-light-9',
]

function applyAccent(hex: string | null) {
  const el = document.documentElement
  if (!hex) {
    // 恢复样式表默认（暗 #3b82f6 / 亮 #2563eb）
    ACCENT_VARS.forEach((name) => el.style.removeProperty(name))
    return
  }
  const dark = state.theme === 'dark'
  const hover = mixHex(hex, '#000000', 0.2)
  el.style.setProperty('--accent', hex)
  el.style.setProperty('--accent-hover', hover)
  el.style.setProperty('--accent-bg', rgba(hex, dark ? 0.1 : 0.08))
  el.style.setProperty('--el-color-primary', hex)
  el.style.setProperty('--el-color-primary-dark-2', hover)
  el.style.setProperty('--el-color-primary-light-3', mixHex(hex, '#ffffff', 0.3))
  el.style.setProperty('--el-color-primary-light-5', mixHex(hex, '#ffffff', 0.5))
  el.style.setProperty('--el-color-primary-light-7', mixHex(hex, '#ffffff', 0.7))
  el.style.setProperty('--el-color-primary-light-8', mixHex(hex, '#ffffff', 0.8))
  el.style.setProperty('--el-color-primary-light-9', rgba(hex, dark ? 0.12 : 0.08))
}

function apply(theme: Theme) {
  state.theme = theme
  localStorage.setItem(THEME_KEY, theme)
  const el = document.documentElement
  el.dataset.theme = theme
  el.classList.toggle('dark', theme === 'dark')
  // 强调色的透明底/浅阶随明暗变化，需按当前主题重算
  applyAccent(state.accent)
}

// 启动时应用持久化的强调色（暗亮由 index.html 内联脚本防闪烁，模块执行早于首次渲染）
applyAccent(state.accent)

export function useThemeStore() {
  return reactive({
    theme: computed(() => state.theme),
    isDark: computed(() => state.theme === 'dark'),
    accent: computed(() => state.accent),
    toggle: () => apply(state.theme === 'dark' ? 'light' : 'dark'),
    setAccent: (hex: string | null) => {
      state.accent = hex
      if (hex) localStorage.setItem(ACCENT_KEY, hex)
      else localStorage.removeItem(ACCENT_KEY)
      applyAccent(hex)
    },
  })
}
