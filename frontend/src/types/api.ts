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
}

// ============ V2 参数回测（字段名/范围/默认值待 C1 定稿，以下为计划第 5 节建议形态）============
// 提交时始终显式传 parameters 走 v2_windowed 语义；字段全部可选，省略项用后端默认值
export interface BacktestParameters {
  initial_cash?: number
  short_window?: number
  long_window?: number
  transaction_cost?: number
  slippage?: number
}
