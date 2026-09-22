<script setup lang="ts">
// 主题色选择器：顶栏色板弹层（参照 KLineChart 官网），与暗/亮切换独立
import { ACCENT_OPTIONS, useThemeStore } from '../../stores/theme'

const theme = useThemeStore()
const DEFAULT_HEX = ACCENT_OPTIONS[0].hex

// 未自定义时默认蓝视为选中态
function isActive(hex: string): boolean {
  return theme.accent ? theme.accent === hex : hex === DEFAULT_HEX
}

function pick(hex: string) {
  // 选默认蓝等同恢复默认（走样式表的双主题取值）
  theme.setAccent(hex === DEFAULT_HEX ? null : hex)
}
</script>

<template>
  <el-popover placement="bottom-end" :width="210" trigger="click">
    <template #reference>
      <button type="button" class="accent-trigger" title="主题色" aria-label="主题色">
        <span class="accent-dot"></span>
      </button>
    </template>

    <div class="panel">
      <div class="swatches" role="radiogroup" aria-label="选择主题色">
        <button
          v-for="opt in ACCENT_OPTIONS"
          :key="opt.hex"
          type="button"
          role="radio"
          :aria-checked="isActive(opt.hex)"
          :class="['swatch', { active: isActive(opt.hex) }]"
          :style="{ background: opt.hex, color: opt.hex }"
          :title="opt.name"
          :aria-label="opt.name"
          @click="pick(opt.hex)"
        >
          <svg
            v-if="isActive(opt.hex)"
            viewBox="0 0 24 24"
            width="12"
            height="12"
            fill="none"
            stroke="#fff"
            stroke-width="3.2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path d="m5 12 5 5 9-10" />
          </svg>
        </button>
      </div>
      <button type="button" class="reset" @click="theme.setAccent(null)">恢复默认</button>
    </div>
  </el-popover>
</template>

<style scoped>
/* 触发按钮：与 ThemeToggle 同规格（32px 方形描边） */
.accent-trigger {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: transparent;
  cursor: pointer;
  transition:
    border-color 0.15s ease,
    background 0.15s ease;
}

.accent-trigger:hover {
  border-color: var(--border-strong);
  background: var(--surface-hover);
}

.accent-dot {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: var(--accent);
  box-shadow:
    inset 0 0 0 1px rgba(255, 255, 255, 0.25),
    0 0 8px color-mix(in srgb, var(--accent) 70%, transparent);
  transition: background 0.2s ease;
}

/* 弹层内容 */
.panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.swatches {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
}

.swatch {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  margin: 0 auto;
  border: none;
  border-radius: 50%;
  cursor: pointer;
  transition:
    transform 0.12s ease,
    box-shadow 0.12s ease;
}

.swatch:hover {
  transform: scale(1.12);
}

/* 选中环：内圈贴弹层底色、外圈用色块本身的颜色 */
.swatch.active {
  box-shadow:
    0 0 0 2px var(--el-bg-color-overlay, var(--surface)),
    0 0 0 4px currentColor;
}

.reset {
  align-self: center;
  padding: 2px 10px;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: var(--text-faint);
  font-size: 12px;
  font-family: inherit;
  cursor: pointer;
  transition: color 0.15s ease;
}

.reset:hover {
  color: var(--accent);
}
</style>
