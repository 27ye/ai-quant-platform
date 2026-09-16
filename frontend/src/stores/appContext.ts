// 应用上下文：记录最近访问的股票代码，供侧栏导航（工作台/回测历史/AI 报告历史）拼链接
// V1 冻结演示默认 600519
import { computed, reactive } from 'vue'

const STORAGE_KEY = 'lastStockCode'

const state = reactive({
  stockCode: localStorage.getItem(STORAGE_KEY) || '600519',
})

export function useAppContext() {
  function setStockCode(code: string) {
    if (!code) return
    state.stockCode = code
    localStorage.setItem(STORAGE_KEY, code)
  }

  return reactive({
    stockCode: computed(() => state.stockCode),
    setStockCode,
  })
}
