<script setup lang="ts">
import { cn } from '../utils/cn'

interface CanaryMetrics {
  passRate: number
  errorRate: number
  p99Latency: string
  memoryPeak: string
}

defineProps<{
  steps: string[]
  completedSteps: string[]
  currentStep: string
  metrics: CanaryMetrics
}>()
</script>

<template>
  <div :class="cn('space-y-3', $attrs.class as string | undefined)">
    <div class="flex gap-1">
      <div
        v-for="step in steps"
        :key="step"
        :class="cn(
          'h-1.5 flex-1 rounded-full',
          completedSteps.includes(step) && 'bg-green-500',
          step === currentStep && 'bg-yellow-500 animate-pulse',
          !completedSteps.includes(step) && step !== currentStep && 'bg-border'
        )"
      />
    </div>
    <div class="flex justify-between text-[10px] text-muted-foreground">
      <span
        v-for="step in steps"
        :key="step"
        :class="cn(step === currentStep && 'text-yellow-500 font-semibold')"
      >
        {{ step }}{{ completedSteps.includes(step) ? ' ✅' : '' }}
      </span>
    </div>
    <div class="grid grid-cols-4 gap-3 text-center">
      <div>
        <div class="text-lg font-bold text-green-500">{{ metrics.passRate }}%</div>
        <div class="text-[10px] text-muted-foreground">通过率</div>
      </div>
      <div>
        <div class="text-lg font-bold text-green-500">{{ metrics.errorRate }}%</div>
        <div class="text-[10px] text-muted-foreground">错误率</div>
      </div>
      <div>
        <div class="text-lg font-bold">{{ metrics.p99Latency }}</div>
        <div class="text-[10px] text-muted-foreground">P99 延迟</div>
      </div>
      <div>
        <div class="text-lg font-bold text-yellow-500">{{ metrics.memoryPeak }}</div>
        <div class="text-[10px] text-muted-foreground">内存峰值</div>
      </div>
    </div>
  </div>
</template>
