import { createRouter, createWebHistory } from 'vue-router'
import { useAppContext } from '../stores/appContext'
import { useHealthStore } from '../stores/health'

// 无壳首页已废除：/ 直接渲染工作台；原 hero（K 线背景 + 品牌标题）移到 /home，在工作台外壳内展示
const StockDetailView = () => import('../views/StockDetailView.vue')
const HomeView = () => import('../views/HomeView.vue')

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      // / 直接渲染工作台；无 :code 参数时回退到最近访问的股票（见 StockDetailView）
      path: '/',
      name: 'root',
      component: StockDetailView,
      beforeEnter: async () => {
        const health = useHealthStore()
        await health.refresh()
        const code = health.acceptanceMode === 'frozen' ? '600519' : useAppContext().stockCode
        return { name: 'stock-detail', params: { code }, replace: true }
      },
    },
    {
      // 品牌首页（hero），侧栏「首页」入口，不离开工作台外壳
      path: '/home',
      name: 'home',
      component: HomeView,
    },
    {
      path: '/stock/:code',
      name: 'stock-detail',
      // 路由复用同一组件实例时（如 /stock/A → /stock/B）需要重新拉数据
      component: StockDetailView,
    },
    // ============ V2 历史页路由 ============
    {
      path: '/stock/:code/news',
      name: 'news',
      component: () => import('../views/NewsView.vue'),
    },
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
