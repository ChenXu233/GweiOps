<script setup lang="ts">
import { toneDot, type Tone } from '../../utils/tone'

withDefaults(
  defineProps<{ tone?: Tone; label?: string; pulse?: boolean }>(),
  { tone: 'idle', pulse: false },
)
</script>

<template>
  <span class="inline-flex items-center gap-1.5 text-[12px] font-medium text-ink-soft">
    <span class="relative flex h-1.5 w-1.5">
      <span
        v-if="pulse"
        class="absolute inline-flex h-full w-full animate-ping rounded-full opacity-60"
        :class="toneDot[tone]"
      />
      <span class="relative inline-flex h-1.5 w-1.5 rounded-full" :class="toneDot[tone]" />
    </span>
    <span class="truncate"><slot>{{ label }}</slot></span>
  </span>
</template>
