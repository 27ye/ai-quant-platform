// V3 F1：本地自选（A1）
// 契约（docs/V3_DEVELOPMENT_PLAN.md §4 F1）：
// - 独立带版本的 localStorage key；保存六位代码/名称/加入时间；按代码去重，最多 20 只，按加入时间排序
// - 缺失或损坏数据不导致页面崩溃：过滤非法条目并提示恢复结果
// - 存储禁用/写入失败时明确提示「本次未持久保存」，页面内继续可用
// - 同一浏览器跨标签页通过 storage 事件同步，不承诺跨设备
// - 加入/移出/展示不额外请求行情
import { computed, reactive } from 'vue'

const STORAGE_KEY = 'watchlist.v1'
export const WATCHLIST_MAX = 20

export interface WatchlistItem {
  /** 六位字符串代码，保留前导零 */
  code: string
  /** 名称可为空串（来源缺失时仅显示代码） */
  name: string
  /** 加入时间戳（ms），排序键 */
  addedAt: number
}

// 单条合法性：代码须为六位数字字符串；名称须为字符串；时间戳须为有限数
function isValidItem(raw: unknown): raw is WatchlistItem {
  if (!raw || typeof raw !== 'object') return false
  const item = raw as Record<string, unknown>
  return (
    typeof item.code === 'string' &&
    /^\d{6}$/.test(item.code) &&
    typeof item.name === 'string' &&
    typeof item.addedAt === 'number' &&
    Number.isFinite(item.addedAt)
  )
}

// 过滤非法条目 + 按代码去重（保留最早加入的一条）+ 按加入时间排序
function normalizeItems(parsed: unknown[]): WatchlistItem[] {
  const byCode = new Map<string, WatchlistItem>()
  for (const raw of parsed) {
    if (!isValidItem(raw)) continue
    const existing = byCode.get(raw.code)
    if (!existing || raw.addedAt < existing.addedAt) byCode.set(raw.code, raw)
  }
  return [...byCode.values()].sort((a, b) => a.addedAt - b.addedAt)
}

interface LoadResult {
  items: WatchlistItem[]
  /** 被过滤/去重掉的条目数，用于恢复提示 */
  removed: number
  /** localStorage 整体不可用（禁用/安全策略） */
  unavailable: boolean
}

function loadFromStorage(): LoadResult {
  let raw: string | null
  try {
    raw = localStorage.getItem(STORAGE_KEY)
  } catch {
    return { items: [], removed: 0, unavailable: true }
  }
  if (!raw) return { items: [], removed: 0, unavailable: false }
  try {
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return { items: [], removed: 1, unavailable: false }
    const items = normalizeItems(parsed)
    return { items, removed: parsed.length - items.length, unavailable: false }
  } catch {
    // 整体损坏：按空列表恢复，提示一次
    return { items: [], removed: 1, unavailable: false }
  }
}

const initial = loadFromStorage()

const state = reactive({
  items: initial.items,
  /** 写入是否成功；false 时页面继续可用但提示「本次未持久保存」 */
  storageOk: !initial.unavailable,
  /** 本次加载过滤掉的损坏/重复条目数（提示一次后清零） */
  recoveredCount: initial.removed,
})

function persist(): boolean {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state.items))
    state.storageOk = true
    return true
  } catch {
    state.storageOk = false
    return false
  }
}

export function useWatchlist() {
  function has(code: string): boolean {
    return state.items.some((item) => item.code === code)
  }

  // 返回 ok 表示是否加入成功；message 为需要提示的文案（含持久化失败提示）
  function add(code: string, name: string): { ok: boolean; message?: string } {
    const cleanCode = code.trim()
    const cleanName = name.trim().slice(0, 40)
    if (!/^\d{6}$/.test(cleanCode)) return { ok: false, message: '自选仅支持六位股票代码' }
    if (has(cleanCode)) return { ok: false, message: '该股票已在自选中' }
    if (state.items.length >= WATCHLIST_MAX) {
      return { ok: false, message: `自选最多保留 ${WATCHLIST_MAX} 只，请先移出部分股票` }
    }
    state.items.push({ code: cleanCode, name: cleanName, addedAt: Date.now() })
    state.items.sort((a, b) => a.addedAt - b.addedAt)
    const saved = persist()
    return saved ? { ok: true } : { ok: true, message: '本地存储不可用，本次未持久保存' }
  }

  function remove(code: string) {
    const index = state.items.findIndex((item) => item.code === code)
    if (index === -1) return
    state.items.splice(index, 1)
    persist()
  }

  function dismissRecovered() {
    state.recoveredCount = 0
  }

  return reactive({
    items: computed(() => state.items),
    storageOk: computed(() => state.storageOk),
    recoveredCount: computed(() => state.recoveredCount),
    has,
    add,
    remove,
    dismissRecovered,
  })
}

// 跨标签页同步：其他标签页写入后重放其存储内容（不承诺跨设备）
if (typeof window !== 'undefined') {
  window.addEventListener('storage', (event) => {
    if (event.key !== STORAGE_KEY) return
    const result = loadFromStorage()
    state.items = result.items
    state.storageOk = !result.unavailable
    if (result.removed > 0) state.recoveredCount = result.removed
  })
}
