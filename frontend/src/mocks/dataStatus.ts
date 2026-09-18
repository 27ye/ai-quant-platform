// V2 数据状态 mock（契约：B 于 Issue #11，docs/API_SPEC.md §4.4）
// 样例对齐 B 给的真实形状：live 模式、stale 15 天（演示黄色「可能非最新」徽标路径）
import type { ApiResponse, DataStatus } from '../types/api'

export function mockDataStatus(stockCode: string): ApiResponse<DataStatus> {
  return {
    code: 0,
    message: 'success',
    data: {
      stock_code: stockCode,
      catalog: {
        synced: true,
        row_count: 5915,
        last_success_at: '2026-09-15T01:20:23Z',
        last_attempt_at: '2026-09-15T01:20:23Z',
        source: 'https://push2delay.eastmoney.com/api/qt/clist/get',
        last_error: null,
      },
      kline: {
        mode: 'live',
        source: 'akshare.stock_zh_a_hist',
        rows: 403,
        first_trade_date: '2025-01-02',
        last_trade_date: '2026-08-31',
        last_refreshed_at: '2026-09-15T01:44:55Z',
        coverage: 'known',
        expected_trading_days: 403,
        last_attempt_at: '2026-09-15T01:44:55Z',
        last_error: null,
        freshness: { status: 'stale', stale_days: 15, max_stale_days: 3 },
      },
      as_of: '2026-09-15T01:50:00Z',
    },
  }
}
