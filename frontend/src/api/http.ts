import axios from 'axios'
import { ElMessage } from 'element-plus'

import type { ApiResponse } from '../types/api'

declare module 'axios' {
  export interface AxiosRequestConfig {
    /** 为 true 时跳过拦截器的统一错误弹窗，由调用方自行处理 */
    skipErrorHandler?: boolean
  }
}

// 空字符串也回退到 /api/v1（D 联调要求）
const baseURL = import.meta.env.VITE_API_BASE_URL
export const http = axios.create({
  baseURL: baseURL || '/api/v1',
  timeout: 10000,
})

// 同一错误短时间内只弹一次，避免并发请求全挂时消息刷屏
let lastMessage = ''
let lastShownAt = 0
function showErrorMessage(message: string) {
  const now = Date.now()
  if (message === lastMessage && now - lastShownAt < 2000) return
  lastMessage = message
  lastShownAt = now
  ElMessage.error(message)
}

// 业务码 → 中文文案（B 联调小抄 v1，message 是固定英文，前端用 code 映射）
const CODE_MESSAGES: Record<number, string> = {
  40001: '参数有误或关键词不能为空',
  40002: '该股票不存在',
  40003: '该股票历史数据不足，无法计算',
  50001: '数据源暂时不可用，请稍后重试',
  50002: '服务暂不可用，请稍后重试',
  50003: '量化计算异常，请稍后重试',
  50005: 'AI 分析失败，可手动重试',
}

function resolveMessage(code: number | undefined, fallback: string): string {
  if (code != null && code in CODE_MESSAGES) return CODE_MESSAGES[code]
  return fallback || '请求失败'
}

// 统一处理业务错误码与网络错误，组件只需处理成功分支
http.interceptors.response.use(
  (response) => {
    const body = response.data as ApiResponse<unknown>
    if (
      !response.config.skipErrorHandler &&
      body &&
      typeof body === 'object' &&
      'code' in body &&
      body.code !== 0
    ) {
      const message = resolveMessage(body.code, body.message)
      showErrorMessage(message)
      return Promise.reject(new Error(message))
    }
    return response
  },
  (error) => {
    if (!error?.config?.skipErrorHandler) {
      const status = error?.response?.status
      const body = error?.response?.data as ApiResponse<unknown> | undefined
      // 非 2xx 也可能携带 ApiResponse 业务码（如 422 + body.code=40003），优先用 code 映射
      if (body && typeof body === 'object' && 'code' in body) {
        showErrorMessage(resolveMessage(body.code, body.message))
      } else {
        showErrorMessage(
          status ? `请求失败（HTTP ${status}）` : '网络错误，请检查后端服务是否启动',
        )
      }
    }
    return Promise.reject(error)
  },
)
