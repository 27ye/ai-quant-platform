<script setup lang="ts">
// 内页布局壳：左侧栏（导航 + 后端状态）+ 顶栏（搜索 + 主题切换）+ 内容区，全站统一（含 /home 品牌首页）
import { computed } from 'vue'
import { useRoute } from 'vue-router'

import { useAppContext } from '../../stores/appContext'
import { useHealthStore } from '../../stores/health'
import SearchBox from './SearchBox.vue'
import ThemeToggle from './ThemeToggle.vue'

const route = useRoute()
const appContext = useAppContext()
const health = useHealthStore()

// 导航项：含股票代码的链接跟随最近访问的股票
const navItems = computed(() => {
  const code = appContext.stockCode
  return [
    { label: '首页', to: '/home', match: (p: string) => p === '/home', icon: 'home' },
    {
      label: '工作台',
      to: `/stock/${code}`,
      // / 也直接渲染工作台（无 :code 时回退最近访问股票），一并高亮
      match: (p: string) => p === '/' || /^\/stock\/[^/]+$/.test(p),
      icon: 'chart',
    },
    {
      label: '新闻资讯',
      to: `/stock/${code}/news`,
      match: (p: string) => /\/stock\/[^/]+\/news$/.test(p),
      icon: 'news',
    },
    {
      label: '回测历史',
      to: `/stock/${code}/backtests`,
      match: (p: string) => p.includes('/backtests'),
      icon: 'history',
    },
    {
      label: 'AI 报告历史',
      to: `/stock/${code}/ai-reports`,
      match: (p: string) => p.includes('/ai-reports') || p.startsWith('/ai/reports'),
      icon: 'report',
    },
  ]
})

const currentPath = computed(() => route.path)
</script>

<template>
  <div class="shell">
    <!-- 左侧栏 -->
    <aside class="sidebar">
      <router-link to="/home" class="brand">
        <span class="brand-mark" aria-hidden="true"></span>
        <span class="brand-name">DeepInSight</span>
      </router-link>

      <nav class="nav">
        <router-link
          v-for="item in navItems"
          :key="item.label"
          :to="item.to"
          :class="['nav-item', { active: item.match(currentPath) }]"
        >
          <!-- 极简线性图标 -->
          <svg v-if="item.icon === 'home'" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path d="M3 10.5 12 3l9 7.5" /><path d="M5 9.5V21h14V9.5" />
          </svg>
          <svg v-else-if="item.icon === 'chart'" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path d="M3 3v18h18" /><path d="m7 14 4-4 3 3 5-6" />
          </svg>
          <svg v-else-if="item.icon === 'news'" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path d="M4 5h13v13a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5z" /><path d="M17 9h3v9a2 2 0 0 1-2 2" /><path d="M8 9h5M8 13h5M8 17h3" />
          </svg>
          <svg v-else-if="item.icon === 'history'" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path d="M3 12a9 9 0 1 0 2.6-6.4" /><path d="M3 4v5h5" /><path d="M12 7v5l3 3" />
          </svg>
          <svg v-else viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" /><path d="M14 3v6h6" /><path d="M9 13h6M9 17h6" />
          </svg>
          <span>{{ item.label }}</span>
        </router-link>
      </nav>

      <!-- 后端连接状态 -->
      <div class="sidebar-footer">
        <span
          :class="['dot', health.status === 'ok' ? 'ok' : 'err']"
          :title="health.status === 'ok' ? '后端已连接' : '后端未连接'"
        ></span>
        <span class="footer-text">{{ health.status === 'ok' ? '后端已连接' : '后端未连接' }}</span>
        <span v-if="health.acceptanceMode" class="mode-tag">{{ health.acceptanceMode }}</span>
      </div>
    </aside>

    <!-- 右侧：顶栏 + 内容 -->
    <div class="main">
      <header class="header">
        <div class="header-search">
          <SearchBox />
        </div>
        <ThemeToggle />
      </header>

      <div class="content">
        <slot />
      </div>
    </div>
  </div>
</template>

<style scoped>
.shell {
  display: flex;
  min-height: 100vh;
}

/* ---- 左侧栏 ---- */
.sidebar {
  position: sticky;
  top: 0;
  display: flex;
  flex-direction: column;
  width: var(--sidebar-width);
  height: 100vh;
  flex-shrink: 0;
  background: var(--surface);
  border-right: 1px solid var(--border);
}

.brand {
  display: flex;
  align-items: center;
  gap: 8px;
  height: var(--header-height);
  padding: 0 16px;
  border-bottom: 1px solid var(--border);
  text-decoration: none;
  flex-shrink: 0;
}

.brand-mark {
  width: 8px;
  height: 8px;
  border-radius: 2px;
  background: var(--accent);
}

.brand-name {
  color: var(--text-main);
  font-size: 14px;
  font-weight: 600;
  letter-spacing: 0.04em;
}

.nav {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 12px 8px;
  flex: 1;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border-radius: 6px;
  color: var(--text-sub);
  font-size: 13px;
  text-decoration: none;
  transition:
    color 0.15s ease,
    background 0.15s ease;
}

.nav-item:hover {
  color: var(--text-main);
  background: var(--surface-hover);
}

.nav-item.active {
  color: var(--accent);
  background: var(--accent-bg);
}

.sidebar-footer {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  border-top: 1px solid var(--border);
  flex-shrink: 0;
}

.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}

.dot.ok {
  background: var(--down);
}

.dot.err {
  background: var(--text-faint);
}

.footer-text {
  color: var(--text-faint);
  font-size: 11px;
}

.mode-tag {
  padding: 1px 6px;
  border: 1px solid var(--accent);
  border-radius: 3px;
  color: var(--accent);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}

/* ---- 右侧 ---- */
.main {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
}

.header {
  position: sticky;
  top: 0;
  z-index: 100;
  display: flex;
  align-items: center;
  gap: 16px;
  height: var(--header-height);
  padding: 0 24px;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
}

.header-search {
  flex: 1;
  max-width: 420px;
}

.content {
  flex: 1;
  min-width: 0;
}

/* 窄屏：隐藏侧栏 */
@media (max-width: 880px) {
  .sidebar {
    display: none;
  }

  .header {
    padding: 0 12px;
  }
}
</style>
