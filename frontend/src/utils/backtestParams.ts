// V2 回测参数表单的客户端校验（提交前拦截，不发请求）
// 约束来源：V2 计划 C1 建议值；字段名/范围/默认值待 C 定稿后同步，常量集中在此便于调整
import type { BacktestParameters } from '../types/api'

export const BACKTEST_PARAM_LIMITS = {
  shortWindowMin: 2,
  longWindowMax: 120,
  maxRangeYears: 5,
} as const

// 表单原始值：数字输入框清空时为 null
export interface BacktestFormValues {
  start_date: string
  end_date: string
  initial_cash: number | null
  short_window: number | null
  long_window: number | null
  transaction_cost: number | null
  slippage: number | null
}

// 返回错误文案列表，空数组表示校验通过
export function validateBacktestForm(values: BacktestFormValues): string[] {
  const errors: string[] = []

  // 日期区间：起 < 止，且不超过 5 年（计划第 5 节：单次请求至多 5 年用户区间）
  if (!values.start_date || !values.end_date) {
    errors.push('请选择回测起止日期')
  } else {
    const start = new Date(values.start_date)
    const end = new Date(values.end_date)
    if (start >= end) {
      errors.push('开始日期必须早于结束日期')
    } else {
      const maxEnd = new Date(start)
      maxEnd.setFullYear(maxEnd.getFullYear() + BACKTEST_PARAM_LIMITS.maxRangeYears)
      if (end > maxEnd) {
        errors.push(`回测区间不能超过 ${BACKTEST_PARAM_LIMITS.maxRangeYears} 年`)
      }
    }
  }

  // 初始资金：正且有限
  if (values.initial_cash == null) {
    errors.push('请填写初始资金')
  } else if (
    !Number.isFinite(values.initial_cash) ||
    values.initial_cash <= 0
  ) {
    errors.push('初始资金必须为大于 0 的有限数值')
  }

  // 均线周期：整数，2 ≤ short < long ≤ 120
  const shortOk =
    values.short_window != null &&
    Number.isInteger(values.short_window) &&
    values.short_window >= BACKTEST_PARAM_LIMITS.shortWindowMin
  const longOk =
    values.long_window != null &&
    Number.isInteger(values.long_window) &&
    values.long_window <= BACKTEST_PARAM_LIMITS.longWindowMax
  if (!shortOk) {
    errors.push(`短均线周期必须为不小于 ${BACKTEST_PARAM_LIMITS.shortWindowMin} 的整数`)
  }
  if (!longOk) {
    errors.push(`长均线周期必须为不超过 ${BACKTEST_PARAM_LIMITS.longWindowMax} 的整数`)
  }
  if (shortOk && longOk && values.short_window! >= values.long_window!) {
    errors.push('短均线周期必须小于长均线周期')
  }

  // 交易成本与滑点：[0, 1)
  for (const [label, value] of [
    ['交易成本', values.transaction_cost],
    ['滑点', values.slippage],
  ] as const) {
    if (value == null) {
      errors.push(`请填写${label}`)
    } else if (!Number.isFinite(value) || value < 0 || value >= 1) {
      errors.push(`${label}必须在 [0, 1) 区间内`)
    }
  }

  return errors
}

// 由校验通过的表单值构造提交参数（配合 start_date/end_date 由调用方补充）
export function toBacktestParameters(values: BacktestFormValues): BacktestParameters {
  return {
    initial_cash: values.initial_cash ?? undefined,
    short_window: values.short_window ?? undefined,
    long_window: values.long_window ?? undefined,
    transaction_cost: values.transaction_cost ?? undefined,
    slippage: values.slippage ?? undefined,
  }
}
