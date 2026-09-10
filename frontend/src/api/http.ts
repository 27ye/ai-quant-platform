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
      const message = body.message || '请求失败'
      showErrorMessage(message)
      return Promise.reject(new Error(message))
    }
    return response
  },
  (error) => {
    if (!error?.config?.skipErrorHandler) {
      const status = error?.response?.status
      // 非 2xx 也可能携带 ApiResponse 业务文案（如 422 + body.code=40003），优先展示
      const bodyMessage: unknown = error?.response?.data?.message
      if (typeof bodyMessage === 'string' && bodyMessage) {
        showErrorMessage(bodyMessage)
      } else {
        showErrorMessage(
          status ? `请求失败（HTTP ${status}）` : '网络错误，请检查后端服务是否启动',
        )
      }
    }
    return Promise.reject(error)
  },
)
