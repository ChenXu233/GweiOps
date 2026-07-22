<script setup lang="ts">
import { cn } from '../utils/cn'

interface TimelineStep {
  id: string
  label: string
  status: 'done' | 'active' | 'pending'
}

defineProps<{
  steps: TimelineStep[]
}>()
</script>

<template>
  <div :class="cn('flex items-center gap-0 overflow-x-auto', $attrs.class as string | undefined)">
    <div v-for="(step, i) in steps" :key="step.id" class="flex items-center">
      <div class="flex items-center gap-2 whitespace-nowrap">
        <div :class="cn(
          'h-2 w-2 rounded-full flex-shrink-0',
          step.status === 'done' && 'bg-green-500',
          step.status === 'active' && 'bg-yellow-500 animate-pulse',
          step.status === 'pending' && 'bg-border'
        )" />
        <span :class="cn(
          'text-xs',
          step.status === 'done' && 'text-muted-foreground',
          step.status === 'active' && 'text-yellow-500 font-semibold',
          step.status === 'pending' && 'text-muted-foreground'
        )">
          {{ step.label }}
        </span>
      </div>
      <div v-if="i < steps.length - 1" class="w-6 h-px bg-border mx-1 flex-shrink-0" />
    </div>
  </div>
</template>
