<script setup lang="ts">
import { cn } from '../utils/cn'

type Status = 'healthy' | 'warning' | 'critical'

const props = withDefaults(defineProps<{
  status: Status
  size?: 'sm' | 'md'
}>(), {
  size: 'sm'
})

const statusColors: Record<Status, string> = {
  healthy: 'bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.6)]',
  warning: 'bg-yellow-500',
  critical: 'bg-red-500',
}
</script>

<template>
  <span :class="cn(
    'inline-block rounded-full',
    props.size === 'sm' ? 'h-1.5 w-1.5' : 'h-2 w-2',
    statusColors[props.status],
    $attrs.class as string | undefined
  )" />
</template>
