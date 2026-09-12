<script setup lang="ts">
import { computed } from 'vue'
import BentoCell from './BentoCell.vue'
import MetricCard from './MetricCard.vue'
import type { PluginWidget } from '../types/repos'

const props = defineProps<{
  widget: PluginWidget
}>()

const span = computed(
  () => Math.min(Math.max(Math.round(props.widget.span) || 1, 1), 4) as 1 | 2 | 3 | 4
)
</script>

<template>
  <BentoCell :span="span">
    <div class="flex items-center justify-between mb-3">
      <div class="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        {{ widget.title }}
      </div>
      <span
        class="text-[9px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground"
        :title="`插件: ${widget.plugin}`"
      >
        插件
      </span>
    </div>

    <div v-if="widget.kind === 'metric'" class="space-y-4">
      <MetricCard
        v-for="(m, i) in widget.metrics"
        :key="i"
        :label="m.label"
        :value="m.value"
        :sub="m.sub"
        :variant="(m.variant as any) || 'default'"
      />
    </div>

    <div v-else-if="widget.kind === 'list'" class="space-y-0">
      <div
        v-for="(item, i) in widget.items"
        :key="i"
        class="text-xs py-2 border-b border-border last:border-0 text-muted-foreground"
      >
        {{ item.text }}
      </div>
    </div>
  </BentoCell>
</template>
