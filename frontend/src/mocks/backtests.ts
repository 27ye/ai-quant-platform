// V2 回测历史 mock（契约：B 于 Issue #11）
// V3 F3：扩充为四条记录，覆盖对照页各状态：
// - 600519：#12 v2 完整快照 / #13 v2 不同参数与资金 / #7 v1 快照缺失
// - 000001：#15 v2 完整快照（跨股票对照演示）
// - 未知 ID：按契约抛 HTTP 404 + code=40005
import { AxiosError } from 'axios'

import type {
  ApiResponse,
  BacktestDetail,
  BacktestSummary,
  PaginatedBacktests,
  TradeRecord,
} from '../types/api'

const SUMMARIES: BacktestSummary[] = [
  {
    backtest_id: 12,
    stock_code: '600519',
    strategy_name: 'ma5_ma20_long_only',
    semantics_version: 'v2_windowed',
    start_date: '2025-07-04',
    end_date: '2026-08-31',
    initial_cash: 100000,
    final_equity: 108340.12,
    total_return: 0.0834,
    annual_return: 0.0791,
    max_drawdown: -0.1203,
    sharpe_ratio: 0.87,
    win_rate: 0.53,
    trade_count: 12,
    order_count: 24,
    benchmark_return: 0.021,
    snapshot_status: 'complete',
    created_at: '2026-09-16T00:12:31Z',
  },
  {
    backtest_id: 13,
    stock_code: '600519',
    strategy_name: 'ma5_ma20_long_only',
    semantics_version: 'v2_windowed',
    start_date: '2025-01-02',
    end_date: '2025-12-31',
    initial_cash: 200000,
    final_equity: 187250.44,
    total_return: -0.0637,
    annual_return: -0.0637,
    max_drawdown: -0.1522,
    sharpe_ratio: 0.31,
    win_rate: 0.5,
    trade_count: 8,
    order_count: 16,
    benchmark_return: -0.021,
    snapshot_status: 'complete',
    created_at: '2026-09-15T10:20:00Z',
  },
  {
    backtest_id: 7,
    stock_code: '600519',
    strategy_name: 'ma5_ma20_long_only',
    semantics_version: 'v1_legacy',
    start_date: '2025-01-02',
    end_date: '2026-08-31',
    initial_cash: 100000,
    final_equity: 90834.23,
    total_return: -0.0917,
    annual_return: null,
    max_drawdown: null,
    sharpe_ratio: null,
    win_rate: null,
    trade_count: 12,
    order_count: 24,
    benchmark_return: null,
    snapshot_status: 'missing',
    created_at: '2026-09-14T09:30:00Z',
  },
  {
    backtest_id: 15,
    stock_code: '000001',
    strategy_name: 'ma5_ma20_long_only',
    semantics_version: 'v2_windowed',
    start_date: '2025-07-04',
    end_date: '2026-08-31',
    initial_cash: 100000,
    final_equity: 103120.4,
    total_return: 0.0312,
    annual_return: 0.0296,
    max_drawdown: -0.0875,
    sharpe_ratio: 0.54,
    win_rate: 0.5,
    trade_count: 10,
    order_count: 20,
    benchmark_return: 0.012,
    snapshot_status: 'complete',
    created_at: '2026-09-13T08:00:00Z',
  },
]

export function mockBacktests(query: {
  stock_code?: string
  page?: number
  page_size?: number
}): ApiResponse<PaginatedBacktests> {
  const page = query.page ?? 1
  const pageSize = query.page_size ?? 20
  const filtered = query.stock_code
    ? SUMMARIES.filter((item) => item.stock_code === query.stock_code)
    : SUMMARIES
  const start = (page - 1) * pageSize
  return {
    code: 0,
    message: 'success',
    data: {
      items: filtered.slice(start, start + pageSize),
      total: filtered.length,
      page,
      page_size: pageSize,
    },
  }
}

// 详情曲线：少量静态点即可，演示用
const EQUITY_CURVE_12 = [
  { trade_date: '2025-07-04', equity: 100000 },
  { trade_date: '2025-09-30', equity: 102410.5 },
  { trade_date: '2025-12-31', equity: 97820.3 },
  { trade_date: '2026-03-31', equity: 105120.8 },
  { trade_date: '2026-06-30', equity: 101540.0 },
  { trade_date: '2026-08-31', equity: 108340.12 },
]

const BENCHMARK_CURVE_12 = [
  { trade_date: '2025-07-04', benchmark_equity: 100000 },
  { trade_date: '2025-09-30', benchmark_equity: 100860.2 },
  { trade_date: '2025-12-31', benchmark_equity: 99450.1 },
  { trade_date: '2026-03-31', benchmark_equity: 101230.6 },
  { trade_date: '2026-06-30', benchmark_equity: 100120.4 },
  { trade_date: '2026-08-31', benchmark_equity: 102100.0 },
]

const DRAWDOWN_CURVE_12 = [
  { trade_date: '2025-07-04', drawdown: 0 },
  { trade_date: '2025-09-30', drawdown: -0.0102 },
  { trade_date: '2025-12-31', drawdown: -0.0448 },
  { trade_date: '2026-03-31', drawdown: -0.0121 },
  { trade_date: '2026-06-30', drawdown: -0.0342 },
  { trade_date: '2026-08-31', drawdown: 0 },
]

const EQUITY_CURVE_13 = [
  { trade_date: '2025-01-02', equity: 200000 },
  { trade_date: '2025-03-31', equity: 194820.15 },
  { trade_date: '2025-06-30', equity: 201360.7 },
  { trade_date: '2025-09-30', equity: 189210.32 },
  { trade_date: '2025-12-31', equity: 187250.44 },
]

const EQUITY_CURVE_15 = [
  { trade_date: '2025-07-04', equity: 100000 },
  { trade_date: '2025-09-30', equity: 101210.8 },
  { trade_date: '2025-12-31', equity: 98540.2 },
  { trade_date: '2026-03-31', equity: 100880.55 },
  { trade_date: '2026-06-30', equity: 102310.9 },
  { trade_date: '2026-08-31', equity: 103120.4 },
]

const TRADES: TradeRecord[] = [
  {
    order_id: 1,
    signal_date: '2025-07-03',
    execution_date: '2025-07-04',
    side: 'buy',
    execution_price: 1420.5,
    shares: 70.38,
    gross_amount: 99999.99,
    fee: 100.0,
    cash_after: 0.01,
    position_after: 1,
    round_trip_pnl: null,
    round_trip_return: null,
  },
  {
    order_id: 2,
    signal_date: '2025-09-29',
    execution_date: '2025-09-30',
    side: 'sell',
    execution_price: 1455.8,
    shares: 70.38,
    gross_amount: 102481.3,
    fee: 102.48,
    cash_after: 102378.82,
    position_after: 0,
    round_trip_pnl: 2378.83,
    round_trip_return: 0.0238,
  },
]

const EXECUTION_ASSUMPTIONS = {
  model: 'research_fractional_v1',
  signal: 'previous_observation_close',
  execution: 'next_observation_open',
  first_day_signal: 'last_warmup_close',
  transaction_cost: 'proportional_on_each_buy_and_sell',
  slippage: 'buy_price_increased_sell_price_decreased',
  fractional_shares: true,
  forced_final_sale: false,
  benchmark_includes_costs: false,
  exchange_execution_constraints: 'not_modelled',
  price_basis: 'qfq',
} as const

// #12：600519 MA 5/20 完整快照
function detail12(summary: BacktestSummary): BacktestDetail {
  return {
    ...summary,
    warmup_start_date: '2025-06-06',
    parameters: {
      ma_short_period: 5,
      ma_long_period: 20,
      initial_cash: 100000,
      transaction_cost: 0.001,
      slippage: 0,
    },
    effective_parameters: {
      ma_short_period: 5,
      ma_long_period: 20,
      initial_cash: 100000,
      transaction_cost: 0.001,
      slippage: 0,
    },
    equity_curve: EQUITY_CURVE_12,
    benchmark_curve: BENCHMARK_CURVE_12,
    drawdown_curve: DRAWDOWN_CURVE_12,
    trades: TRADES,
    data_meta: {
      requested_start_date: '2025-07-04',
      requested_end_date: '2026-08-31',
      actual_start_date: '2025-07-04',
      actual_end_date: '2026-08-31',
      rows: 403,
      rows_in_window: 288,
      warmup_required_days: 20,
      window_owner: 'c',
      frame_digest: 'b3f7c2a1d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1',
      c_data_hash: '9af45d325e7cced7fc420da9f502e3abcf72ede1b7ad95070b264f8b0c4052f4',
    },
    current_position: 0,
    c_result_available: true,
    c_result_exact: true,
    c_algorithm_version: 'v2.0.0',
    c_data_hash: '9af45d325e7cced7fc420da9f502e3abcf72ede1b7ad95070b264f8b0c4052f4',
    c_initial_equity: {
      trade_date: '2025-07-04',
      equity: 100000,
      valuation: 'before_open',
    },
    c_warmup: {
      start_date: '2025-06-06',
      end_date: '2025-07-03',
      required_rows: 20,
      used_rows: 20,
    },
    c_execution_assumptions: EXECUTION_ASSUMPTIONS,
    c_semantics_version: 'v2_windowed',
    input_snapshot_available: true,
    input_snapshot_rows: 403,
  }
}

// #13：600519 MA 10/40、初始资金 20 万、区间不同（对照演示：参数/资金/区间差异）
function detail13(summary: BacktestSummary): BacktestDetail {
  return {
    ...summary,
    warmup_start_date: '2024-11-08',
    parameters: {
      ma_short_period: 10,
      ma_long_period: 40,
      initial_cash: 200000,
      transaction_cost: 0.001,
      slippage: 0,
    },
    effective_parameters: {
      ma_short_period: 10,
      ma_long_period: 40,
      initial_cash: 200000,
      transaction_cost: 0.001,
      slippage: 0,
    },
    equity_curve: EQUITY_CURVE_13,
    benchmark_curve: [
      { trade_date: '2025-01-02', benchmark_equity: 200000 },
      { trade_date: '2025-12-31', benchmark_equity: 195800.0 },
    ],
    drawdown_curve: [
      { trade_date: '2025-01-02', drawdown: 0 },
      { trade_date: '2025-12-31', drawdown: -0.0637 },
    ],
    trades: TRADES.slice(0, 1),
    data_meta: {
      requested_start_date: '2025-01-02',
      requested_end_date: '2025-12-31',
      actual_start_date: '2025-01-02',
      actual_end_date: '2025-12-31',
      rows: 512,
      rows_in_window: 242,
      warmup_required_days: 40,
      window_owner: 'c',
      frame_digest: 'c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2',
      c_data_hash: '51b02e8f4a7c9d1e3f5a7b9c1d3e5f7a9c1d3e5f7a9c1d3e5f7a9c1d3e5f7a9c',
    },
    current_position: 0,
    c_result_available: true,
    c_result_exact: true,
    c_algorithm_version: 'v2.0.0',
    c_data_hash: '51b02e8f4a7c9d1e3f5a7b9c1d3e5f7a9c1d3e5f7a9c1d3e5f7a9c1d3e5f7a9c',
    c_initial_equity: {
      trade_date: '2025-01-02',
      equity: 200000,
      valuation: 'before_open',
    },
    c_warmup: {
      start_date: '2024-11-08',
      end_date: '2024-12-31',
      required_rows: 40,
      used_rows: 40,
    },
    c_execution_assumptions: EXECUTION_ASSUMPTIONS,
    c_semantics_version: 'v2_windowed',
    input_snapshot_available: true,
    input_snapshot_rows: 512,
  }
}

// #15：000001 完整快照（跨股票对照演示）
function detail15(summary: BacktestSummary): BacktestDetail {
  return {
    ...summary,
    warmup_start_date: '2025-06-06',
    parameters: {
      ma_short_period: 5,
      ma_long_period: 20,
      initial_cash: 100000,
      transaction_cost: 0.001,
      slippage: 0,
    },
    effective_parameters: {
      ma_short_period: 5,
      ma_long_period: 20,
      initial_cash: 100000,
      transaction_cost: 0.001,
      slippage: 0,
    },
    equity_curve: EQUITY_CURVE_15,
    benchmark_curve: [
      { trade_date: '2025-07-04', benchmark_equity: 100000 },
      { trade_date: '2026-08-31', benchmark_equity: 101200.0 },
    ],
    drawdown_curve: [
      { trade_date: '2025-07-04', drawdown: 0 },
      { trade_date: '2026-08-31', drawdown: -0.0312 },
    ],
    trades: TRADES.slice(0, 1),
    data_meta: {
      requested_start_date: '2025-07-04',
      requested_end_date: '2026-08-31',
      actual_start_date: '2025-07-04',
      actual_end_date: '2026-08-31',
      rows: 403,
      rows_in_window: 288,
      warmup_required_days: 20,
      window_owner: 'c',
      frame_digest: 'd4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6',
      c_data_hash: '77c19f3a6e2d8b4c0a5f1e9d3b7a6c5e4f2d1b0a9c8e7d6f5a4b3c2d1e0f9a8b7',
    },
    current_position: 0,
    c_result_available: true,
    c_result_exact: true,
    c_algorithm_version: 'v2.0.0',
    c_data_hash: '77c19f3a6e2d8b4c0a5f1e9d3b7a6c5e4f2d1b0a9c8e7d6f5a4b3c2d1e0f9a8b7',
    c_initial_equity: {
      trade_date: '2025-07-04',
      equity: 100000,
      valuation: 'before_open',
    },
    c_warmup: {
      start_date: '2025-06-06',
      end_date: '2025-07-03',
      required_rows: 20,
      used_rows: 20,
    },
    c_execution_assumptions: EXECUTION_ASSUMPTIONS,
    c_semantics_version: 'v2_windowed',
    input_snapshot_available: true,
    input_snapshot_rows: 403,
  }
}

export function mockBacktestDetail(backtestId: number): ApiResponse<BacktestDetail> {
  const summary = SUMMARIES.find((item) => item.backtest_id === backtestId)
  if (!summary) {
    // 未知 ID：按契约 HTTP 404 + code=40005（backtest not found）
    throw new AxiosError(
      'Request failed with status code 404',
      AxiosError.ERR_BAD_REQUEST,
      undefined,
      undefined,
      {
        status: 404,
        statusText: 'Not Found',
        data: { code: 40005, message: 'backtest not found' },
        headers: {},
        config: {} as never,
      },
    )
  }
  if (summary.snapshot_status === 'missing') {
    // V1 旧记录：只有摘要指标，无快照
    return {
      code: 0,
      message: 'success',
      data: {
        ...summary,
        warmup_start_date: null,
        parameters: null,
        effective_parameters: null,
        equity_curve: null,
        benchmark_curve: null,
        drawdown_curve: null,
        trades: null,
        data_meta: null,
        current_position: null,
        snapshot_missing_reason: 'V1 记录仅保存摘要指标，未保存完整快照',
      },
    }
  }
  if (backtestId === 13) return { code: 0, message: 'success', data: detail13(summary) }
  if (backtestId === 15) return { code: 0, message: 'success', data: detail15(summary) }
  return { code: 0, message: 'success', data: detail12(summary) }
}
