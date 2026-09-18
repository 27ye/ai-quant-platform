// V2 A3：回测历史（契约已定稿：B 于 Issue #11）
// GET /backtests 列表 + GET /backtests/{id} 详情，均为只读回放，不重算
import { http } from './http'
import { useMockFor } from './mockSwitch'
import { mockBacktestDetail, mockBacktests } from '../mocks/backtests'
import type { ApiResponse, BacktestDetail, PaginatedBacktests } from '../types/api'

export interface BacktestListQuery {
  stock_code?: string
  page?: number
  page_size?: number
}

// 分页结构 data:{items,total,page,page_size}；排序固定 created_at DESC, id DESC
export async function fetchBacktests(
  query: BacktestListQuery = {},
): Promise<ApiResponse<PaginatedBacktests>> {
  if (useMockFor('BACKTESTS')) return mockBacktests(query)
  const response = await http.get<ApiResponse<PaginatedBacktests>>('/backtests', {
    params: query,
  })
  return response.data
}

// 未知 ID → HTTP 404 + code=40005（backtest not found）
export async function fetchBacktestDetail(
  backtestId: number,
): Promise<ApiResponse<BacktestDetail>> {
  if (useMockFor('BACKTESTS')) return mockBacktestDetail(backtestId)
  const response = await http.get<ApiResponse<BacktestDetail>>(`/backtests/${backtestId}`)
  return response.data
}
