import { http } from './http'
import { useMockFor } from './mockSwitch'
import { mockNews } from '../mocks/news'
import type { ApiResponse, NewsItem } from '../types/api'

// GET /stocks/{stock_code}/news（V1 计划接口，字段按后端 stock_news 模型契约）
export async function fetchNews(
  stockCode: string,
  limit = 20,
): Promise<ApiResponse<NewsItem[]>> {
  if (useMockFor('NEWS')) return mockNews(stockCode, limit)
  const response = await http.get<ApiResponse<NewsItem[]>>(
    `/stocks/${stockCode}/news`,
    { params: { limit } },
  )
  return response.data
}
