<script setup lang="ts">
import { cn } from '../../utils/cn'

withDefaults(defineProps<{
  as?: string
  class?: string
}>(), {
  as: 'button'
})
</script>

<template>
  <component
    :is="as"
    :class="cn(
      'inline-flex items-center justify-center whitespace-nowrap rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 bg-primary text-primary-foreground shadow hover:bg-primary/90 h-9 px-4 py-2',
      $props.class
    )"
  >
    <slot />
  </component>
</template>
