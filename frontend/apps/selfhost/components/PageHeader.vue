<script setup lang="ts">
/** 统一的页头:眉标 + 标题 + 一句话说明 + 右侧动作位。 */
defineProps<{ eyebrow?: string; title: string; description?: string }>()
</script>

<template>
  <header class="flex flex-wrap items-end justify-between gap-3">
    <div class="min-w-0">
      <div v-if="eyebrow" class="eyebrow">{{ eyebrow }}</div>
      <h1 class="page-title mt-2">{{ title }}</h1>
      <p v-if="description" class="page-desc">{{ description }}</p>
    </div>
    <div v-if="$slots.actions" class="flex shrink-0 items-center gap-2">
      <slot name="actions" />
    </div>
  </header>
</template>
