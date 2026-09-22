<script setup lang="ts">
// V3 F1：本地自选条（工作台紧凑区域，A1）
// 只读展示 + 本地增删，不请求行情；点击自选股进入对应工作台。
// 冻结验收模式下不能通过自选入口绕过可打开股票的限制。
import { computed, h } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { useAppContext } from '../../stores/appContext'
import { useHealthStore } from '../../stores/health'
import { useWatchlist, WATCHLIST_MAX } from '../../stores/watchlist'

const props = defineProps<{ stockCode: string }>()

const router = useRouter()
const health = useHealthStore()
const appContext = useAppContext()
const watchlist = useWatchlist()

const inWatchlist = computed(() => watchlist.has(props.stockCode))

// 移除后 3.5s 内可撤销：恢复原名称的自选条目
function notifyRemoved(code: string, name: string) {
  ElMessage({
    type: 'success',
    duration: 3500,
    message: h('span', { class: 'wl-toast' }, [
      h('span', null, '已移出自选'),
      h(
        'button',
        {
          type: 'button',
          class: 'wl-toast-undo',
          onClick: () => watchlist.add(code, name),
        },
        '撤销',
      ),
    ]),
  })
}

function toggleCurrent() {
  if (inWatchlist.value) {
    const name = appContext.resolveStockName(props.stockCode)
    watchlist.remove(props.stockCode)
    notifyRemoved(props.stockCode, name)
    return
  }
  const result = watchlist.add(
    props.stockCode,
    appContext.resolveStockName(props.stockCode),
  )
  if (result.message) ElMessage.info(result.message)
  else ElMessage.success('已加入自选')
}

function openStock(code: string) {
  // 冻结模式限制可打开股票（与路由 / 的回退口径一致），自选入口不得绕过
  if (health.acceptanceMode === 'frozen' && code !== '600519') {
    ElMessage.warning('冻结演示仅包含 600519，未命中其他股票')
    return
  }
  router.push(`/stock/${code}`)
}

function removeItem(code: string) {
  const name = watchlist.items.find((item) => item.code === code)?.name ?? ''
  watchlist.remove(code)
  notifyRemoved(code, name)
}
</script>

<template>
  <section class="watchlist-strip" aria-label="本地自选">
    <span class="strip-label">
      自选
      <span class="strip-count">{{ watchlist.items.length }}/{{ WATCHLIST_MAX }}</span>
    </span>

    <div class="strip-body">
      <span v-if="watchlist.items.length === 0" class="empty-hint">
        暂无自选，点击右侧加入当前股票
      </span>
      <ul v-else class="chip-list">
        <li v-for="item in watchlist.items" :key="item.code" class="chip-item">
          <button type="button" class="chip" @click="openStock(item.code)">
            <span class="chip-name">{{ item.name || item.code }}</span>
            <span class="chip-code">{{ item.code }}</span>
          </button>
          <button
            type="button"
            class="chip-remove"
            :aria-label="`移出自选 ${item.code}`"
            @click.stop="removeItem(item.code)"
          >
            ×
          </button>
        </li>
      </ul>
    </div>

    <button
      type="button"
      class="toggle-add"
      :class="{ active: inWatchlist }"
      @click="toggleCurrent"
    >
      {{ inWatchlist ? '★ 移出自选' : '☆ 加入自选' }}
    </button>

    <!-- 恢复提示：本次加载过滤掉损坏/重复条目，提示一次可关闭 -->
    <div v-if="watchlist.recoveredCount > 0" class="strip-notice">
      已忽略 {{ watchlist.recoveredCount }} 条损坏或重复的自选数据
      <button type="button" class="notice-dismiss" @click="watchlist.dismissRecovered()">
        知道了
      </button>
    </div>
    <!-- 持久化失败：继续可用但明示未保存，不显示保存成功 -->
    <div v-else-if="!watchlist.storageOk" class="strip-notice">
      本地存储不可用，自选修改本次未持久保存
    </div>
  </section>
</template>

<style scoped>
.watchlist-strip {
  position: relative;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  padding: 8px 14px;
  margin-bottom: 14px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
}

.strip-label {
  display: flex;
  flex-direction: column;
  gap: 1px;
  color: var(--text-main);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.04em;
  white-space: nowrap;
}

.strip-count {
  color: var(--text-faint);
  font-size: 10px;
  font-weight: 400;
  font-variant-numeric: tabular-nums;
}

.strip-body {
  flex: 1;
  min-width: 0;
}

.empty-hint {
  color: var(--text-faint);
  font-size: 12px;
}

.chip-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  list-style: none;
  margin: 0;
  padding: 0;
  /* 预留提示行高度对齐 */
  max-height: 58px;
  overflow-y: auto;
}

.chip-list::-webkit-scrollbar {
  width: 5px;
}

.chip-list::-webkit-scrollbar-thumb {
  background: var(--border-strong);
  border-radius: 3px;
}

.chip-item {
  position: relative;
  display: inline-flex;
}

.chip {
  display: inline-flex;
  align-items: baseline;
  gap: 6px;
  padding: 3px 22px 3px 10px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--bg);
  cursor: pointer;
  font: inherit;
  transition:
    border-color 0.15s ease,
    background 0.15s ease;
}

.chip:hover {
  border-color: var(--accent);
  background: var(--accent-bg);
}

.chip-name {
  color: var(--text-main);
  font-size: 12px;
}

.chip-code {
  color: var(--text-faint);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

.chip-remove {
  position: absolute;
  top: 50%;
  right: 4px;
  transform: translateY(-50%);
  padding: 0 2px;
  border: none;
  background: none;
  color: var(--text-faint);
  font-size: 13px;
  line-height: 1;
  cursor: pointer;
  /* 常显低透明度（触屏无 hover 也可点），hover 提亮 */
  opacity: 0.45;
  transition:
    color 0.15s ease,
    opacity 0.15s ease;
}

.chip-item:hover .chip-remove {
  opacity: 1;
}

.chip-remove:hover {
  color: var(--up);
}

.toggle-add {
  flex-shrink: 0;
  padding: 4px 12px;
  border: 1px solid var(--accent);
  border-radius: 6px;
  background: transparent;
  color: var(--accent);
  font-size: 12px;
  white-space: nowrap;
  cursor: pointer;
  transition:
    background 0.15s ease,
    color 0.15s ease;
}

.toggle-add:hover {
  background: var(--accent);
  color: var(--bg);
}

.toggle-add.active {
  border-color: var(--border-strong);
  color: var(--text-sub);
}

.toggle-add.active:hover {
  border-color: var(--up);
  color: var(--up);
}

.strip-notice {
  /* 卡片内第二行展示提示，不再绝对定位压到下方卡 */
  flex-basis: 100%;
  display: flex;
  align-items: center;
  gap: 8px;
  padding-top: 8px;
  border-top: 1px dashed var(--border);
  color: var(--text-faint);
  font-size: 11px;
}

/* ElMessage 内的撤销按钮（scoped 无法作用，用全局类） */
:global(.wl-toast) {
  display: inline-flex;
  align-items: center;
  gap: 10px;
}

:global(.wl-toast-undo) {
  padding: 0;
  border: none;
  background: none;
  color: var(--el-color-primary);
  font: inherit;
  cursor: pointer;
}

:global(.wl-toast-undo:hover) {
  text-decoration: underline;
}

.notice-dismiss {
  padding: 0;
  border: none;
  background: none;
  color: var(--accent);
  font-size: 11px;
  cursor: pointer;
}

.notice-dismiss:hover {
  text-decoration: underline;
}

@media (max-width: 760px) {
  .watchlist-strip {
    flex-wrap: wrap;
  }

  .strip-body {
    order: 3;
    flex-basis: 100%;
  }

  .toggle-add {
    margin-left: auto;
  }
}
</style>
