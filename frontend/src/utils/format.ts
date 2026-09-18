import type { SourceMode, TrendValue } from '../types/api'

export function formatPercent(value: number): string {
  return `${(value * 100).toFixed(2)}%`
}

// ISO 时间字符串 → 本地 'YYYY-MM-DD HH:mm'，空值显示占位符
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

// A 股配色习惯：看涨红、看跌绿
export const TREND_LABEL: Record<TrendValue, string> = {
  bullish: '看涨',
  neutral: '中性',
  bearish: '看跌',
}

export const SOURCE_MODE_LABEL: Record<SourceMode, string> = {
  live: '实时',
  cache: '缓存',
  frozen: '冻结',
  unknown: '未知来源',
}
