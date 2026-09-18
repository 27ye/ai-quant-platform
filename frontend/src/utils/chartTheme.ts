// 图表调色板：从当前生效的 CSS 变量读取（暗/亮主题切换后需重新调用并重建 option）
// 语义来源见 styles.css 的 :root 与 [data-theme="light"]
export interface ChartPalette {
  up: string
  down: string
  accent: string
  textMain: string
  textSub: string
  textFaint: string
  border: string
  borderStrong: string
  surface: string
  surfaceHover: string
}

export function chartPalette(): ChartPalette {
  const s = getComputedStyle(document.documentElement)
  const v = (name: string, fallback: string) => s.getPropertyValue(name).trim() || fallback
  return {
    up: v('--up', '#ef4444'),
    down: v('--down', '#10b981'),
    accent: v('--accent', '#3b82f6'),
    textMain: v('--text-main', '#fafafa'),
    textSub: v('--text-sub', '#a1a1aa'),
    textFaint: v('--text-faint', '#71717a'),
    border: v('--border', '#27272a'),
    borderStrong: v('--border-strong', '#3f3f46'),
    surface: v('--surface', '#18181b'),
    surfaceHover: v('--surface-hover', '#27272a'),
  }
}

// hex (#rgb/#rrggbb) 转 rgba，用于面积渐变等需要透明度的场景
export function hexToRgba(hex: string, alpha: number): string {
  const h = hex.replace('#', '')
  const full = h.length === 3 ? h.split('').map((c) => c + c).join('') : h
  const num = Number.parseInt(full, 16)
  if (Number.isNaN(num)) return hex
  const r = (num >> 16) & 255
  const g = (num >> 8) & 255
  const b = num & 255
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}
