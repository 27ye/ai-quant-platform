// 应用上下文：记录最近访问的股票代码，供侧栏导航（工作台/回测历史/AI 报告历史）拼链接
// V1 冻结演示默认 600519
// V3 F1：附带 code→name 映射（来自搜索结果，零额外请求），供自选等本地功能取名称
import { computed, reactive } from 'vue'

const STORAGE_KEY = 'lastStockCode'
const NAMES_KEY = 'stockNames.v1'

const state = reactive({
  stockCode: localStorage.getItem(STORAGE_KEY) || '600519',
})

// code→name 映射：搜索联想结果顺手登记，不额外请求行情
const names = reactive<Record<string, string>>(loadNames())

function loadNames(): Record<string, string> {
  try {
    const raw = localStorage.getItem(NAMES_KEY)
    if (!raw) return {}
    const parsed: unknown = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {}
    const result: Record<string, string> = {}
    for (const [code, name] of Object.entries(parsed as Record<string, unknown>)) {
      if (/^\d{6}$/.test(code) && typeof name === 'string' && name) result[code] = name
    }
    return result
  } catch {
    return {}
  }
}

function persistNames() {
  try {
    localStorage.setItem(NAMES_KEY, JSON.stringify(names))
  } catch {
    // 存储不可用时仅内存保留，不阻断功能
  }
}

export function useAppContext() {
  function setStockCode(code: string) {
    if (!code) return
    state.stockCode = code
    try {
      localStorage.setItem(STORAGE_KEY, code)
    } catch {
      // 同上：存储不可用时仅内存保留
    }
  }

  // 批量登记搜索结果中的名称（SearchBox 调用；数据来自已发出的搜索请求）
  function rememberStockNames(list: Array<{ stock_code: string; stock_name: string }>) {
    let changed = false
    for (const { stock_code, stock_name } of list) {
      if (/^\d{6}$/.test(stock_code) && stock_name && names[stock_code] !== stock_name) {
        names[stock_code] = stock_name
        changed = true
      }
    }
    if (changed) persistNames()
  }

  return reactive({
    stockCode: computed(() => state.stockCode),
    names: computed(() => names),
    setStockCode,
    rememberStockNames,
  })
}
