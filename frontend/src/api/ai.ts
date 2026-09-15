import { http } from './http'
import { useMockFor } from './mockSwitch'
import { mockAIAnalysis, mockAIReportDetail, mockAIReports } from '../mocks/ai'
import type {
  AIAnalysisData,
  AIReportDetail,
  ApiResponse,
  PaginatedAIReports,
} from '../types/api'

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

// ============ V2 AI 报告历史（D 契约已定稿，只读 GET，不触发 LLM/行情/量化）============

// GET /ai/reports：stock_code 可选；page 默认 1，page_size 默认 20、最大 100
export async function fetchAIReports(
  params: { stock_code?: string; page?: number; page_size?: number } = {},
): Promise<ApiResponse<PaginatedAIReports>> {
  if (useMockFor('AI_REPORTS')) return mockAIReports(params)
  const response = await http.get<ApiResponse<PaginatedAIReports>>('/ai/reports', {
    params,
  })
  return response.data
}

// GET /ai/reports/{report_id}：未知 ID 返回 404 + code=40005
export async function fetchAIReportDetail(
  reportId: number,
): Promise<ApiResponse<AIReportDetail>> {
  if (useMockFor('AI_REPORTS')) return mockAIReportDetail(reportId)
  const response = await http.get<ApiResponse<AIReportDetail>>(
    `/ai/reports/${reportId}`,
  )
  return response.data
}
