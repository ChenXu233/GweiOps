<script setup lang="ts">
import { cn } from '../../utils/cn'

withDefaults(defineProps<{
  variant?: 'default' | 'secondary' | 'destructive' | 'outline'
  class?: string
}>(), {
  variant: 'default'
})
</script>

<template>
  <span :class="cn(
    'inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold transition-colors',
    variant === 'default' && 'border-transparent bg-primary text-primary-foreground shadow',
    variant === 'secondary' && 'border-transparent bg-secondary text-secondary-foreground',
    variant === 'outline' && 'text-foreground',
    variant === 'destructive' && 'border-transparent bg-destructive text-destructive-foreground shadow',
    $props.class
  )">
    <slot />
  </span>
</template>
