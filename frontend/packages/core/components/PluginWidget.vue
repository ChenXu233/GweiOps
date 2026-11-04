<script setup lang="ts">
import type { PluginWidget } from '../../types/plugin'

const props = defineProps<{ widget: PluginWidget }>()

const variantClass: Record<string, string> = {
  green: 'text-ok',
  yellow: 'text-amber',
  red: 'text-coral',
}

function valueClass(variant?: string) {
  return (variant && variantClass[variant]) || 'text-ink'
}

// 单指标时铺满整行,否则会留下一个空格子
const metricCols = computed(() => ((props.widget.metrics?.length ?? 0) <= 1 ? 'grid-cols-1' : 'grid-cols-2'))
</script>

<template>
  <div class="flex flex-col">
    <div class="flex items-center justify-between gap-3 border-b border-line px-5 py-3.5">
      <h2 class="truncate text-[13px] font-semibold">{{ widget.title }}</h2>
      <span class="mono-label shrink-0">{{ widget.plugin }}</span>
    </div>

    <div v-if="widget.kind === 'metric'" class="grid gap-px bg-line" :class="metricCols">
      <div v-for="m in widget.metrics" :key="m.label" class="bg-panel px-4 py-3">
        <div class="mono-label truncate">{{ m.label }}</div>
        <div class="mt-1.5 flex items-baseline gap-1">
          <span class="num text-[19px] font-semibold leading-none tracking-tight" :class="valueClass(m.variant)">
            {{ m.value }}
          </span>
          <span v-if="m.sub" class="truncate text-[11px] text-ink-faint">{{ m.sub }}</span>
        </div>
      </div>
    </div>

    <ul v-else class="divide-y divide-line/70">
      <li
        v-for="(item, i) in widget.items"
        :key="i"
        class="flex items-center gap-2 px-5 py-2.5 text-[12.5px] text-ink-soft"
      >
        <span class="h-1 w-1 shrink-0 rounded-full bg-ink-faint" />
        <span class="truncate">{{ item.text }}</span>
      </li>
    </ul>
  </div>
</template>
