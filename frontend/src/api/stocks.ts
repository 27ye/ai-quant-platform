import { http } from './http'
import { useMockFor } from './mockSwitch'
import { mockBacktest, mockIndicators, mockKline, mockScore, mockSearch } from '../mocks/stock'
import { mockDataStatus } from '../mocks/dataStatus'
import type {
  ApiResponse,
  BacktestData,
  BacktestRequest,
  DataStatus,
  IndicatorsItem,
  KlineItem,
  ScoreData,
  StockBrief,
} from '../types/api'

export async function searchStocks(keyword: string): Promise<ApiResponse<StockBrief[]>> {
  if (useMockFor('SEARCH')) return mockSearch(keyword)
  const response = await http.get<ApiResponse<StockBrief[]>>('/stocks/search', {
    params: { keyword },
  })
  return response.data
}

export async function fetchKline(
  stockCode: string,
  params: { start_date?: string; end_date?: string } = {},
): Promise<ApiResponse<KlineItem[]>> {
  if (useMockFor('KLINE')) return mockKline()
  const response = await http.get<ApiResponse<KlineItem[]>>(
    `/stocks/${stockCode}/kline`,
    { params },
  )
  return response.data
}

export async function fetchIndicators(
  stockCode: string,
): Promise<ApiResponse<IndicatorsItem[]>> {
  if (useMockFor('INDICATORS')) return mockIndicators()
  const response = await http.get<ApiResponse<IndicatorsItem[]>>(
    `/stocks/${stockCode}/indicators`,
  )
  return response.data
}

export async function fetchScore(stockCode: string): Promise<ApiResponse<ScoreData>> {
  if (useMockFor('SCORE')) return mockScore(stockCode)
  const response = await http.get<ApiResponse<ScoreData>>(`/stocks/${stockCode}/score`)
  return response.data
}

// V2：payload 省略 parameters → v1_legacy；显式传 parameters（含空对象）→ v2_windowed
// 注意：v2_windowed 在 C 引擎未就绪时返回 50004，且不产生记录
export async function runBacktest(payload: BacktestRequest): Promise<ApiResponse<BacktestData>> {
  if (useMockFor('BACKTEST')) return mockBacktest(payload)
  const response = await http.post<ApiResponse<BacktestData>>('/backtests', payload)
  return response.data
}

// V2 A1：数据状态（GET /stocks/{code}/data-status），驱动工作台数据徽标
export async function fetchDataStatus(stockCode: string): Promise<ApiResponse<DataStatus>> {
  if (useMockFor('DATA_STATUS')) return mockDataStatus(stockCode)
  const response = await http.get<ApiResponse<DataStatus>>(
    `/stocks/${stockCode}/data-status`,
  )
  return response.data
}
