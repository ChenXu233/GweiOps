<script setup lang="ts">
import { useTheme } from '@gwei/core/composables/useTheme'

const props = withDefaults(defineProps<{ collapsed?: boolean }>(), { collapsed: false })

const { mode, set } = useTheme()

const options = [
  { key: 'light' as const, icon: 'sun', label: '亮色' },
  { key: 'dark' as const, icon: 'moon', label: '暗色' },
  { key: 'system' as const, icon: 'system', label: '跟随系统' },
]

const current = computed(() => options.find((o) => o.key === mode.value) ?? options[2])

// 收成图标轨时只留一个按钮:点一下切到下一个模式,当前的模式就是图标本身。
function cycle() {
  const i = options.findIndex((o) => o.key === mode.value)
  const next = options[(i + 1) % options.length]
  if (next) set(next.key)
}
</script>

<template>
  <button
    v-if="props.collapsed"
    class="grid h-9 w-9 place-items-center rounded-xl text-ink-faint transition-colors duration-200 ease-[var(--ease)] hover:bg-well hover:text-ink"
    :aria-label="'外观:' + current.label"
    :title="'外观:' + current.label"
    @click="cycle"
  >
    <AppIcon :name="current.icon" :size="16" />
  </button>

  <div
    v-else
    class="flex w-fit items-center gap-0.5 rounded-full border border-line bg-panel/70 p-0.5"
    role="group"
    aria-label="外观"
  >
    <button
      v-for="t in options"
      :key="t.key"
      class="grid h-7 w-7 place-items-center rounded-full transition-colors duration-200 ease-[var(--ease)]"
      :class="mode === t.key ? 'bg-ink text-paper' : 'text-ink-faint hover:text-ink'"
      :aria-label="t.label"
      :title="t.label"
      @click="set(t.key)"
    >
      <AppIcon :name="t.icon" :size="13" />
    </button>
  </div>
</template>
