import { http } from './http'
import { useMockFor } from './mockSwitch'
import {
  mockBacktest,
  mockIndicators,
  mockKline,
  mockScore,
  mockSearch,
  mockStockInfo,
} from '../mocks/stock'
import { mockDataStatus } from '../mocks/dataStatus'
import type { AxiosRequestConfig } from 'axios'
import type {
  ApiResponse,
  BacktestData,
  BacktestRequest,
  DataStatus,
  IndicatorsItem,
  KlineItem,
  ScoreData,
  StockBrief,
  StockInfo,
} from '../types/api'

export async function searchStocks(
  keyword: string,
  config?: AxiosRequestConfig,
): Promise<ApiResponse<StockBrief[]>> {
  if (useMockFor('SEARCH')) return mockSearch(keyword)
  const response = await http.get<ApiResponse<StockBrief[]>>('/stocks/search', {
    params: { keyword },
    ...config,
  })
  return response.data
}

// 单只股票详情：走实时 provider（含腾讯/东财延迟主机回退），不依赖本地目录同步，
// 因此目录未同步（搜索 50006）时工作台仍能拿到股票名称。
// 实时源偶发短时抖动（502/50001），静默重试 2 次（调用方一般传 skipErrorHandler）
const STOCK_INFO_MAX_ATTEMPTS = 3
const STOCK_INFO_RETRY_BASE_MS = 900

function delay(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

export async function fetchStockInfo(
  stockCode: string,
  config?: AxiosRequestConfig,
): Promise<ApiResponse<StockInfo>> {
  if (useMockFor('STOCK_INFO')) return mockStockInfo(stockCode)
  let lastError: unknown
  for (let attempt = 0; attempt < STOCK_INFO_MAX_ATTEMPTS; attempt += 1) {
    try {
      const response = await http.get<ApiResponse<StockInfo>>(
        `/stocks/${stockCode}`,
        config,
      )
      return response.data
    } catch (error) {
      lastError = error
      if (attempt < STOCK_INFO_MAX_ATTEMPTS - 1) {
        await delay(STOCK_INFO_RETRY_BASE_MS * (attempt + 1))
      }
    }
  }
  throw lastError
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
  config?: AxiosRequestConfig,
): Promise<ApiResponse<IndicatorsItem[]>> {
  if (useMockFor('INDICATORS')) return mockIndicators()
  const response = await http.get<ApiResponse<IndicatorsItem[]>>(
    `/stocks/${stockCode}/indicators`,
    config,
  )
  return response.data
}

export async function fetchScore(
  stockCode: string,
  config?: AxiosRequestConfig,
): Promise<ApiResponse<ScoreData>> {
  if (useMockFor('SCORE')) return mockScore(stockCode)
  const response = await http.get<ApiResponse<ScoreData>>(
    `/stocks/${stockCode}/score`,
    config,
  )
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
export async function fetchDataStatus(
  stockCode: string,
  config?: AxiosRequestConfig,
): Promise<ApiResponse<DataStatus>> {
  if (useMockFor('DATA_STATUS')) return mockDataStatus(stockCode)
  const response = await http.get<ApiResponse<DataStatus>>(
    `/stocks/${stockCode}/data-status`,
    config,
  )
  return response.data
}
