import { computed, reactive } from 'vue'

import { fetchHealth } from '../api/health'

const state = reactive({
  status: 'unknown',
  acceptanceMode: '',
  loading: false,
  error: '',
})

export function useHealthStore() {
  async function refresh() {
    state.loading = true
    state.error = ''
    try {
      const result = await fetchHealth()
      // 代理返回异常体时 data 可能为空，兜底避免控制台报错
      state.status = result.data?.status ?? 'unavailable'
      state.acceptanceMode = result.data?.acceptance_mode ?? ''
    } catch (error) {
      state.status = 'unavailable'
      state.acceptanceMode = ''
      state.error = error instanceof Error ? error.message : 'health check failed'
    } finally {
      state.loading = false
    }
  }

  // 包 reactive 让模板和脚本里直接拿到解包后的值，而不是 ComputedRef 对象
  return reactive({
    status: computed(() => state.status),
    acceptanceMode: computed(() => state.acceptanceMode),
    loading: computed(() => state.loading),
    error: computed(() => state.error),
    refresh,
  })
}
