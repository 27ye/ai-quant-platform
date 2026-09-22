import { createRouter, createWebHistory } from 'vue-router'
import { useAppContext } from '../stores/appContext'
import { useHealthStore } from '../stores/health'

// 无壳首页已废除：/ 直接渲染工作台；原 hero（K 线背景 + 品牌标题）移到 /home，在工作台外壳内展示
const StockDetailView = () => import('../views/StockDetailView.vue')
const HomeView = () => import('../views/HomeView.vue')

const router = createRouter({
  history: createWebHistory(),
  // 前进/新开页面回到顶部；浏览器后退/前进恢复原位置
  scrollBehavior(_to, _from, savedPosition) {
    return savedPosition ?? { top: 0 }
  },
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
      meta: { title: '首页' },
    },
    {
      path: '/stock/:code',
      name: 'stock-detail',
      // 路由复用同一组件实例时（如 /stock/A → /stock/B）需要重新拉数据
      component: StockDetailView,
      meta: { title: '工作台' },
    },
    // ============ V2 历史页路由 ============
    {
      path: '/stock/:code/news',
      name: 'news',
      component: () => import('../views/NewsView.vue'),
      meta: { title: '新闻资讯' },
    },
    {
      path: '/stock/:code/backtests',
      name: 'backtest-history',
      component: () => import('../views/BacktestHistoryView.vue'),
      meta: { title: '回测历史' },
    },
    {
      // V3 F3：两个历史回测对照（静态段优先于 /backtests/:id 参数段）
      path: '/backtests/compare',
      name: 'backtest-compare',
      component: () => import('../views/BacktestCompareView.vue'),
      meta: { title: '回测对照' },
    },
    {
      path: '/backtests/:id',
      name: 'backtest-detail',
      component: () => import('../views/BacktestDetailView.vue'),
      meta: { title: '回测详情' },
    },
    {
      path: '/stock/:code/ai-reports',
      name: 'ai-report-history',
      component: () => import('../views/AIReportHistoryView.vue'),
      meta: { title: 'AI 报告历史' },
    },
    {
      path: '/ai/reports/:id',
      name: 'ai-report-detail',
      component: () => import('../views/AIReportDetailView.vue'),
      meta: { title: 'AI 报告详情' },
    },
    {
      // 未匹配路径：展示 404 页而非静默跳首页
      path: '/:pathMatch(.*)*',
      name: 'not-found',
      component: () => import('../views/NotFoundView.vue'),
      meta: { title: '页面不存在' },
    },
  ],
})

// 按路由更新浏览器标签标题
router.afterEach((to) => {
  document.title = to.meta.title ? `${to.meta.title} · DeepInSight` : 'DeepInSight'
})

export default router
