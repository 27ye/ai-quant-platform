<script setup lang="ts">
// 内页布局壳：左侧栏（导航 + 后端状态）+ 顶栏（搜索 + 主题切换）+ 内容区，全站统一（含 /home 品牌首页）
// ≤880px 侧栏收起，顶栏出现汉堡按钮打开导航抽屉
import { ref } from 'vue'

import SearchBox from './SearchBox.vue'
import ThemeToggle from './ThemeToggle.vue'
import AccentPicker from './AccentPicker.vue'
import SidebarContent from './SidebarContent.vue'

// 团队仓库入口（顶栏右侧）
const REPO_URL = 'https://github.com/27ye/ai-quant-platform'

const drawerOpen = ref(false)
</script>

<template>
  <div class="shell">
    <!-- 桌面左侧栏 -->
    <aside class="sidebar">
      <SidebarContent />
    </aside>

    <!-- 移动导航抽屉（≤880px） -->
    <el-drawer v-model="drawerOpen" direction="ltr" size="240px" :with-header="false" class="nav-drawer">
      <SidebarContent @navigate="drawerOpen = false" />
    </el-drawer>

    <!-- 右侧：顶栏 + 内容 -->
    <div class="main">
      <header class="header">
        <button
          type="button"
          class="menu-btn"
          aria-label="打开导航菜单"
          @click="drawerOpen = true"
        >
          <svg viewBox="0 0 24 24" width="19" height="19" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
            <path d="M4 7h16M4 12h16M4 17h16" />
          </svg>
        </button>
        <div class="header-search">
          <SearchBox />
        </div>
        <div class="header-actions">
          <a
            class="github-link"
            :href="REPO_URL"
            target="_blank"
            rel="noopener noreferrer"
            title="GitHub 仓库"
          >
            <svg viewBox="0 0 16 16" width="15" height="15" fill="currentColor" aria-hidden="true">
              <path
                d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z"
              />
            </svg>
            <span>GitHub</span>
          </a>
          <AccentPicker />
          <ThemeToggle />
        </div>
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
  width: var(--sidebar-width);
  height: 100vh;
  flex-shrink: 0;
  background: var(--surface);
  border-right: 1px solid var(--border);
}

/* 抽屉体去掉默认内边距，铺满侧栏内容 */
.nav-drawer :deep(.el-drawer__body) {
  padding: 0;
  background: var(--surface);
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

/* 汉堡按钮：默认隐藏，窄屏出现 */
.menu-btn {
  display: none;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  flex-shrink: 0;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: transparent;
  color: var(--text-sub);
  cursor: pointer;
  transition:
    color 0.15s ease,
    border-color 0.15s ease;
}

.menu-btn:hover {
  color: var(--text-main);
  border-color: var(--border-strong);
}

.header-search {
  flex: 1;
  max-width: 420px;
}

/* 顶栏右侧操作区：GitHub 入口 + 主题色 + 明暗切换，整体贴最右 */
.header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
  margin-left: auto;
}

.github-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  padding: 0 10px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: transparent;
  color: var(--text-sub);
  font-size: 12.5px;
  font-weight: 500;
  text-decoration: none;
  transition:
    color 0.15s ease,
    border-color 0.15s ease,
    background 0.15s ease;
}

.github-link:hover {
  color: var(--text-main);
  border-color: var(--border-strong);
  background: var(--surface-hover);
}

.content {
  flex: 1;
  min-width: 0;
}

/* 窄屏：隐藏侧栏，汉堡按钮出现 */
@media (max-width: 880px) {
  .sidebar {
    display: none;
  }

  .menu-btn {
    display: inline-flex;
  }

  .header {
    gap: 10px;
    padding: 0 12px;
  }

  /* 小屏 GitHub 只留图标 */
  .github-link {
    padding: 0;
    width: 32px;
    justify-content: center;
  }

  .github-link span {
    display: none;
  }
}
</style>
