// V2 回测历史 mock（契约：B 于 Issue #11）
// 覆盖两种记录形态：id=12 v2_windowed 完整快照 + id=7 v1_legacy 快照缺失
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
const EQUITY_CURVE = [
  { trade_date: '2025-07-04', equity: 100000 },
  { trade_date: '2025-09-30', equity: 102410.5 },
  { trade_date: '2025-12-31', equity: 97820.3 },
  { trade_date: '2026-03-31', equity: 105120.8 },
  { trade_date: '2026-06-30', equity: 101540.0 },
  { trade_date: '2026-08-31', equity: 108340.12 },
]

const BENCHMARK_CURVE = [
  { trade_date: '2025-07-04', benchmark_equity: 100000 },
  { trade_date: '2025-09-30', benchmark_equity: 100860.2 },
  { trade_date: '2025-12-31', benchmark_equity: 99450.1 },
  { trade_date: '2026-03-31', benchmark_equity: 101230.6 },
  { trade_date: '2026-06-30', benchmark_equity: 100120.4 },
  { trade_date: '2026-08-31', benchmark_equity: 102100.0 },
]

const DRAWDOWN_CURVE = [
  { trade_date: '2025-07-04', drawdown: 0 },
  { trade_date: '2025-09-30', drawdown: -0.0102 },
  { trade_date: '2025-12-31', drawdown: -0.0448 },
  { trade_date: '2026-03-31', drawdown: -0.0121 },
  { trade_date: '2026-06-30', drawdown: -0.0342 },
  { trade_date: '2026-08-31', drawdown: 0 },
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

export function mockBacktestDetail(backtestId: number): ApiResponse<BacktestDetail> {
  if (backtestId === 7) {
    // V1 旧记录：只有摘要指标，无快照
    const summary = SUMMARIES[1]
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
  const summary = SUMMARIES[0]
  return {
    code: 0,
    message: 'success',
    data: {
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
      equity_curve: EQUITY_CURVE,
      benchmark_curve: BENCHMARK_CURVE,
      drawdown_curve: DRAWDOWN_CURVE,
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
      c_algorithm_version: 'v2.0.0',
      c_semantics_version: 'v2_windowed',
      input_snapshot_available: true,
      input_snapshot_rows: 403,
    },
  }
}
