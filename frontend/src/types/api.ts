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

// ============ V2 AI 报告历史（契约已定稿：D 的 docs/V2_AI_REPORT_HISTORY_CONTRACT.md / PR #10）============

export type SourceMode = 'live' | 'cache' | 'frozen' | 'unknown'
export type SnapshotStatus = 'complete' | 'legacy_missing'

// GET /ai/reports 列表项（仅摘要，不含完整上下文）
export interface AIReportSummary {
  report_id: number
  stock_code: string
  quant_score: number | null
  trend: TrendValue
  summary: string
  model_name: string
  data_as_of: string | null
  created_at: string
  source_mode: SourceMode
  snapshot_status: SnapshotStatus
}

// GET /ai/reports 分页包装
export interface PaginatedAIReports {
  items: AIReportSummary[]
  total: number
  page: number
  page_size: number
}

// 上下文快照内的结构化数据（与后端 schemas/ai.py 对齐）
export interface ContextStock {
  stock_code: string
  stock_name: string
  industry: string | null
}

export interface ContextMarketSnapshot {
  trade_date: string
  close: number | null
  change_pct: number | null
  turnover_rate: number | null
}

export interface ContextQuantScore {
  score: number
  level: string
  reasons: string[]
}

export interface ContextBacktestMetrics {
  strategy_name: string
  start_date: string
  end_date: string
  total_return: number | null
  annual_return: number | null
  max_drawdown: number | null
  sharpe_ratio: number | null
  win_rate: number | null
  trade_count: number | null
  benchmark_return: number | null
}

// 数据来源证明：报告生成时实际使用的数据口径
export interface DataProvenance {
  source_mode: SourceMode
  provider: string
  market_start_date: string
  market_end_date: string
  market_rows: number
  news_status: 'available' | 'empty'
  news_count: number
  retrieved_at: string
}

export interface AnalysisContextSnapshot {
  stock: ContextStock
  market_snapshot: ContextMarketSnapshot
  technical_indicators: IndicatorsItem | null
  quant_score: ContextQuantScore | null
  backtest_metrics: ContextBacktestMetrics | null
  news: NewsItem[]
  data_as_of: string
  provenance: DataProvenance
}

// POST /ai/analyze 的 V2 响应 / GET /ai/reports/{report_id} 详情（两者同构）
// V1 旧记录：snapshot_status='legacy_missing'，context_snapshot/版本字段为 null，source_mode='unknown'
export interface AIReportDetail extends AIAnalysisData {
  report_id: number
  created_at: string
  data_as_of: string | null
  source_mode: SourceMode
  prompt_version: string | null
  context_schema_version: string | null
  output_schema_version: string | null
  context_hash: string | null
  snapshot_status: SnapshotStatus
  context_snapshot: AnalysisContextSnapshot | null
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
  // ---- V2 新增（可选，C 已定稿字段口径；B 的响应包装确认后转为必填项核对）----
  backtest_id?: number
  semantics_version?: 'v1_legacy' | 'v2_windowed'
  benchmark_curve?: BenchmarkCurvePoint[]
  drawdown_curve?: DrawdownCurvePoint[]
  trades?: TradeRecord[]
  /** 成交记录条数（区别于 trade_count = 已完成买卖往返次数） */
  order_count?: number
}

// ============ V2 参数化回测（契约已定稿：C 于 Issue #11 确认）============

/**
 * 回测参数白名单（POST /backtests 请求体 parameters 字段，V1 冻结演示不含此块）
 * C 定稿口径：页面内部可用 short/long/commission 变量，提交时映射为以下字段名；
 * 页面显示百分数（如 0.1%），发送小数（0.001）。默认值 5 / 20 / 100000 / 0.001 / 0。
 * 语义：显式传 parameters（含 {}）→ v2_windowed；完全省略 → v1_legacy；null 无效。
 */
export interface BacktestParameters {
  /** 短期均线窗口，整数 2 <= short < long <= 120 */
  ma_short_period: number
  /** 长期均线窗口 */
  ma_long_period: number
  /** 初始资金，正有限数 */
  initial_cash: number
  /** 交易成本率，有限数 [0,1) */
  transaction_cost: number
  /** 滑点率，有限数 [0,1) */
  slippage: number
}

/** 回测请求体：日期为顶层字段（YYYY-MM-DD，首尾包含，允许单日，最长五个日历年） */
export interface BacktestRequest {
  stock_code: string
  start_date?: string
  end_date?: string
  parameters?: BacktestParameters
}

/** 成交记录（V2 响应 trades 数组元素；买入行 round_trip_* 为 null，卖出行含双边成本） */
export interface TradeRecord {
  /** 本次回测内序号 */
  order_id: number
  signal_date: string
  execution_date: string
  side: 'buy' | 'sell'
  execution_price: number
  /** 允许小数 */
  shares: number
  gross_amount: number
  fee: number
  cash_after: number
  /** 0=空仓 1=持仓（状态，不是股数） */
  position_after: 0 | 1
  round_trip_pnl: number | null
  round_trip_return: number | null
}

/** 基准曲线点：首个有效回测日开盘买入并持有，不含成本滑点（页面标注「买入持有基准（不含成本）」） */
export interface BenchmarkCurvePoint {
  trade_date: string
  benchmark_equity: number
}

/** 回撤曲线点：非正比例值 */
export interface DrawdownCurvePoint {
  trade_date: string
  drawdown: number
}
