<script setup lang="ts">
import { cn } from '../utils/cn'

const props = withDefaults(defineProps<{
  span?: 1 | 2 | 3 | 4
  rowSpan?: 1 | 2
}>(), {
  span: 1,
  rowSpan: 1
})
</script>

<template>
  <div :class="cn(
    'bg-card p-5 flex flex-col',
    props.span === 2 && 'md:col-span-2',
    props.span === 3 && 'md:col-span-2 xl:col-span-3',
    props.span === 4 && 'md:col-span-2 xl:col-span-4',
    props.rowSpan === 2 && 'row-span-2',
    $attrs.class as string | undefined
  )">
    <slot />
  </div>
</template>
