<script setup lang="ts">
withDefaults(
  defineProps<{ icon?: string; title?: string; hint?: string }>(),
  { icon: 'inbox', title: '这里什么都没有' },
)
</script>

<template>
  <div class="flex flex-col items-center justify-center gap-3 px-6 py-16 text-center">
    <span class="grid h-11 w-11 place-items-center rounded-full border border-line bg-well text-ink-faint">
      <AppIcon :name="icon" :size="18" />
    </span>
    <p class="text-[13px] font-medium text-ink-soft">{{ title }}</p>
    <p v-if="hint" class="max-w-xs text-[12px] leading-relaxed text-ink-faint">{{ hint }}</p>
    <slot />
  </div>
</template>
