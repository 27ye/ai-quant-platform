// V2 回测参数表单的客户端校验（提交前拦截，不发请求）
// 契约已定稿：C 于 Issue #11 确认。
// 字段名映射（页面内部 → 请求体）：short_window → ma_short_period、
// long_window → ma_long_period；页面显示百分数（如 0.1%），发送小数（0.001）。
// V3 F5（A3）：新增 strategy 选择 ma_cross | macd，白名单随策略切换（§5.1 契约）。
import type { BacktestParameters, BacktestStrategy, MacdParameters } from '../types/api'

export const BACKTEST_PARAM_LIMITS = {
  shortWindowMin: 2,
  longWindowMax: 120,
  maxRangeYears: 5,
  macdPeriodMin: 2,
  macdPeriodMax: 120,
} as const

// C 定稿默认值：5 / 20 / 100000 / 0.001 / 0
export const BACKTEST_PARAM_DEFAULTS = {
  ma_short_period: 5,
  ma_long_period: 20,
  initial_cash: 100000,
  transaction_cost: 0.001,
  slippage: 0,
} as const

// V3 F5 契约默认值：12 / 26 / 9
export const MACD_PARAM_DEFAULTS = {
  macd_fast_period: 12,
  macd_slow_period: 26,
  macd_signal_period: 9,
} as const

const DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/

// 严格解析 YYYY-MM-DD：拒绝其他格式（如 2025/07/04）和不存在的日期（如 2025-02-30）
function parseDateStrict(value: string): { y: number; m: number; d: number } | null {
  const match = DATE_RE.exec(value)
  if (!match) return null
  const y = Number(match[1])
  const m = Number(match[2])
  const d = Number(match[3])
  if (m < 1 || m > 12) return null
  const daysInMonth = new Date(y, m, 0).getDate()
  if (d < 1 || d > daysInMonth) return null
  return { y, m, d }
}

// 表单原始值：数字输入框清空时为 null
export interface BacktestFormValues {
  strategy: BacktestStrategy
  start_date: string
  end_date: string
  initial_cash: number | null
  /** MA 专有（ma_cross） */
  short_window: number | null
  long_window: number | null
  /** MACD 专有（macd） */
  macd_fast: number | null
  macd_slow: number | null
  macd_signal: number | null
  transaction_cost: number | null
  slippage: number | null
}

// 返回错误文案列表，空数组表示校验通过
export function validateBacktestForm(values: BacktestFormValues): string[] {
  const errors: string[] = []

  // 日期区间：严格 YYYY-MM-DD 真实日期；起 <= 止（C 定稿允许单日）；最长五个日历年
  if (!values.start_date || !values.end_date) {
    errors.push('请选择回测起止日期')
  } else {
    const start = parseDateStrict(values.start_date)
    const end = parseDateStrict(values.end_date)
    if (!start || !end) {
      errors.push('日期须为 YYYY-MM-DD 格式的真实日期')
    } else {
      const startTime = new Date(start.y, start.m - 1, start.d).getTime()
      const endTime = new Date(end.y, end.m - 1, end.d).getTime()
      if (startTime > endTime) {
        errors.push('开始日期不能晚于结束日期')
      } else {
        // 五个日历年：目标年无 2 月 29 日时钳制到 2 月 28 日
        //（不能用 setFullYear，它会把 2020-02-29 + 5 年顺延到 2025-03-01，多放行一天）
        const maxYear = start.y + BACKTEST_PARAM_LIMITS.maxRangeYears
        const maxDaysInMonth = new Date(maxYear, start.m, 0).getDate()
        const maxEnd = new Date(
          maxYear,
          start.m - 1,
          Math.min(start.d, maxDaysInMonth),
        ).getTime()
        if (endTime > maxEnd) {
          errors.push(`回测区间不能超过 ${BACKTEST_PARAM_LIMITS.maxRangeYears} 个日历年`)
        }
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

  // 策略专有参数：白名单随策略切换
  if (values.strategy === 'ma_cross') {
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
  } else {
    // MACD：整数，2 ≤ fast < slow ≤ 120、2 ≤ signal ≤ 120（契约 §5.1）
    const { macdPeriodMin, macdPeriodMax } = BACKTEST_PARAM_LIMITS
    const fastOk =
      values.macd_fast != null &&
      Number.isInteger(values.macd_fast) &&
      values.macd_fast >= macdPeriodMin
    const slowOk =
      values.macd_slow != null &&
      Number.isInteger(values.macd_slow) &&
      values.macd_slow <= macdPeriodMax
    const signalOk =
      values.macd_signal != null &&
      Number.isInteger(values.macd_signal) &&
      values.macd_signal >= macdPeriodMin &&
      values.macd_signal <= macdPeriodMax
    if (!fastOk) {
      errors.push(`MACD 快线周期必须为不小于 ${macdPeriodMin} 的整数`)
    }
    if (!slowOk) {
      errors.push(`MACD 慢线周期必须为不超过 ${macdPeriodMax} 的整数`)
    }
    if (fastOk && slowOk && values.macd_fast! >= values.macd_slow!) {
      errors.push('MACD 快线周期必须小于慢线周期')
    }
    if (!signalOk) {
      errors.push(`MACD 信号线周期必须为 ${macdPeriodMin} ~ ${macdPeriodMax} 的整数`)
    }
  }

  // 交易成本与滑点：有限数值 [0, 1)
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

// 由校验通过的表单值构造 MA 请求体 parameters（调用前须先经 validateBacktestForm 通过）
export function toBacktestParameters(values: BacktestFormValues): BacktestParameters {
  return {
    ma_short_period: values.short_window!,
    ma_long_period: values.long_window!,
    initial_cash: values.initial_cash!,
    transaction_cost: values.transaction_cost!,
    slippage: values.slippage!,
  }
}

// 由校验通过的表单值构造 MACD 请求体 parameters（共同参数仅资金/成本/滑点）
export function toMacdParameters(values: BacktestFormValues): MacdParameters {
  return {
    macd_fast_period: values.macd_fast!,
    macd_slow_period: values.macd_slow!,
    macd_signal_period: values.macd_signal!,
    initial_cash: values.initial_cash!,
    transaction_cost: values.transaction_cost!,
    slippage: values.slippage!,
  }
}
