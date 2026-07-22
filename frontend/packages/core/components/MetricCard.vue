<script setup lang="ts">
import { cn } from '../utils/cn'

type Variant = 'default' | 'green' | 'yellow' | 'red'

const variantColors: Record<Variant, string> = {
  default: 'text-foreground',
  green: 'text-green-500',
  yellow: 'text-yellow-500',
  red: 'text-red-500',
}

const props = withDefaults(defineProps<{
  label: string
  value: string | number
  suffix?: string
  sub?: string
  variant?: Variant
}>(), {
  variant: 'default'
})
</script>

<template>
  <div :class="cn('space-y-1', $attrs.class as string | undefined)">
    <div v-if="props.label" class="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
      {{ props.label }}
    </div>
    <div :class="cn('text-3xl font-bold tracking-tight', variantColors[props.variant])">
      {{ props.value }}
      <span v-if="props.suffix" class="text-base text-muted-foreground ml-0.5">{{ props.suffix }}</span>
    </div>
    <div v-if="props.sub" class="text-xs text-muted-foreground">{{ props.sub }}</div>
  </div>
</template>
