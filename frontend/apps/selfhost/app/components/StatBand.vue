<script setup lang="ts">
/**
 * 概览数字带。全站只有这一种"一眼看完"的写法。
 *
 * 之前四个页面各写各的:控制室用四个 tile、执行记录用三个 tile、
 * 信号源用一条竖线分隔的 inset、待放行用手写的 panel + 大数字。
 * 同一个意思长了四张脸,这里收敛成一个组件。
 */
export interface StatItem {
  label: string
  value: string | number
  unit?: string
  hint?: string
  icon?: string
  tone?: 'default' | 'ok' | 'warn' | 'bad' | 'brand'
}

withDefaults(defineProps<{ stats: StatItem[]; columns?: 2 | 3 | 4 }>(), { columns: 4 })

const toneClass: Record<string, string> = {
  default: '',
  ok: 'text-ok',
  warn: 'text-amber',
  bad: 'text-coral',
  brand: 'text-brand',
}

const colClass: Record<number, string> = {
  2: 'sm:grid-cols-2',
  3: 'sm:grid-cols-3',
  4: 'grid-cols-2 sm:grid-cols-2 lg:grid-cols-4',
}
</script>

<template>
  <div class="grid gap-4" :class="colClass[columns]">
    <div v-for="s in stats" :key="s.label" class="stat">
      <div class="flex items-center justify-between gap-2">
        <span class="eyebrow">{{ s.label }}</span>
        <AppIcon v-if="s.icon" :name="s.icon" :size="13" class="text-ink-faint" />
      </div>

      <div class="mt-3 flex items-baseline gap-1">
        <span
          class="num text-[24px] font-semibold leading-none tracking-tight"
          :class="toneClass[s.tone ?? 'default']"
        >{{ s.value }}</span>
        <span v-if="s.unit" class="text-[11.5px] text-ink-faint">{{ s.unit }}</span>
      </div>

      <p v-if="s.hint" class="mt-2 text-[12px] leading-relaxed text-ink-faint">{{ s.hint }}</p>
    </div>
  </div>
</template>