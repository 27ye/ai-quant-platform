import { http } from './http'
import type { ApiResponse, HealthData } from '../types/api'

export async function fetchHealth(): Promise<ApiResponse<HealthData>> {
  // 健康检查自带状态标签展示，跳过全局错误弹窗
  const response = await http.get<ApiResponse<HealthData>>('/health', {
    skipErrorHandler: true,
  })
  // D 的验收模式通过响应头传递（live / frozen）
  const mode = (response.headers?.['x-acceptance-mode'] as string) || undefined
  if (mode) {
    response.data.data = { ...response.data.data, acceptance_mode: mode }
  }
  return response.data
}
