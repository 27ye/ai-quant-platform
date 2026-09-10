import { http } from './http'
import { useMockFor } from './mockSwitch'
import { mockAIAnalysis } from '../mocks/ai'
import type { AIAnalysisData, ApiResponse } from '../types/api'

// LLM 分析耗时较长（10~30s+），D 联调要求 120s，仅手动重试
const AI_TIMEOUT_MS = 120_000

export async function analyzeStock(
  stockCode: string,
): Promise<ApiResponse<AIAnalysisData>> {
  if (useMockFor('AI')) return mockAIAnalysis(stockCode)
  const response = await http.post<ApiResponse<AIAnalysisData>>(
    '/ai/analyze',
    { stock_code: stockCode },
    { timeout: AI_TIMEOUT_MS },
  )
  return response.data
}
