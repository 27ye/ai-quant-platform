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
    // ============ V2 历史页路由 ============
    {
      path: '/stock/:code/backtests',
      name: 'backtest-history',
      component: () => import('../views/BacktestHistoryView.vue'),
    },
    {
      path: '/backtests/:id',
      name: 'backtest-detail',
      component: () => import('../views/BacktestDetailView.vue'),
    },
    {
      path: '/stock/:code/ai-reports',
      name: 'ai-report-history',
      component: () => import('../views/AIReportHistoryView.vue'),
    },
    {
      path: '/ai/reports/:id',
      name: 'ai-report-detail',
      component: () => import('../views/AIReportDetailView.vue'),
    },
    {
      // 未匹配路径一律回首页
      path: '/:pathMatch(.*)*',
      redirect: '/',
    },
  ],
})

export default router
