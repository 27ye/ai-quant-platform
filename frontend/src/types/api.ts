// 字段均按 docs/API_SPEC.md 契约定义，契约变更时需同步团队
export interface ApiResponse<T> {
  code: number
  message: string
  data: T
}

export interface HealthData {
  status: 'ok' | string
  acceptance_mode?: string
}

// GET /stocks/search
export interface StockBrief {
  stock_code: string
  stock_name: string
}

// GET /stocks/{stock_code}/kline（日期 YYYY-MM-DD，百分比用小数）
export interface KlineItem {
  trade_date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  amount: number
  turnover_rate: number
  change_pct: number
}

// GET /stocks/{stock_code}/indicators（指标存在预热期，未满窗口时后端返回 null）
export interface IndicatorsItem {
  trade_date: string
  ma5: number | null
  ma10: number | null
  ma20: number | null
  ma60: number | null
  macd: number | null
  macd_signal: number | null
  macd_hist: number | null
  rsi14: number | null
  boll_upper: number | null
  boll_middle: number | null
  boll_lower: number | null
}

// GET /stocks/{stock_code}/score（分项上限 40/25/20/15，总分 0-100）
export interface ScoreData {
  stock_code: string
  score: number
  trend_score: number
  momentum_score: number
  volume_score: number
  risk_score: number
  level: string
  reasons: string[]
}

// GET /stocks/{stock_code}/news（按后端 stock_news 模型字段，契约以 API_SPEC + 团队确认为准）
export interface NewsItem {
  title: string
  summary: string | null
  source: string | null
  publish_time: string | null // ISO 字符串，前端按需格式化
  url: string | null
}

// POST /ai/analyze
export type TrendValue = 'bullish' | 'neutral' | 'bearish'

export interface AIAnalysisData {
  stock_code: string
  quant_score: number | null
  trend: TrendValue
  summary: string
  technical_analysis: string
  quant_analysis: string
  news_analysis: string
  advantages: string[]
  risks: string[]
  conclusion: string
  model_name: string
}

// POST /backtests（口径已经 C 契约回归确认：指标为扁平字段；equity 为账户绝对权益，
// initial_cash 起步；sharpe_ratio/win_rate 数据不足时为 null；equity_curve 必填）
export interface BacktestData {
  stock_code: string
  initial_cash: number
  final_equity: number
  total_return: number
  annual_return: number
  max_drawdown: number
  sharpe_ratio: number | null
  win_rate: number | null
  trade_count: number
  equity_curve: Array<{ trade_date: string; equity: number }>
}
