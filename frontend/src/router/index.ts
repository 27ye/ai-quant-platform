import { createRouter, createWebHistory } from 'vue-router'

import HomeView from '../views/HomeView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'home',
      component: HomeView,
    },
    {
      path: '/stock/:code',
      name: 'stock-detail',
      // 路由复用同一组件实例时（如 /stock/A → /stock/B）需要重新拉数据
      component: () => import('../views/StockDetailView.vue'),
    },
    // ============ V2 历史页路由（占位视图，M2 接入真实接口后替换为独立页面）============
    {
      path: '/stock/:code/backtests',
      name: 'backtest-history',
      component: () => import('../views/HistoryPlaceholderView.vue'),
      props: { title: '回测历史', plannedApi: 'GET /api/v1/backtests' },
    },
    {
      path: '/backtests/:id',
      name: 'backtest-detail',
      component: () => import('../views/HistoryPlaceholderView.vue'),
      props: { title: '回测详情', plannedApi: 'GET /api/v1/backtests/{id}' },
    },
    {
      path: '/stock/:code/ai-reports',
      name: 'ai-report-history',
      component: () => import('../views/HistoryPlaceholderView.vue'),
      props: { title: 'AI 报告历史', plannedApi: 'GET /api/v1/ai/reports' },
    },
    {
      path: '/ai/reports/:id',
      name: 'ai-report-detail',
      component: () => import('../views/HistoryPlaceholderView.vue'),
      props: { title: 'AI 报告详情', plannedApi: 'GET /api/v1/ai/reports/{id}' },
    },
    {
      // 未匹配路径一律回首页
      path: '/:pathMatch(.*)*',
      redirect: '/',
    },
  ],
})

export default router
