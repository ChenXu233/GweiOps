<script setup lang="ts">
import { cn } from '../utils/cn'
</script>

<template>
  <div :class="cn('grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-px bg-border rounded-xl overflow-hidden', $attrs.class as string | undefined)">
    <slot />
  </div>
</template>
