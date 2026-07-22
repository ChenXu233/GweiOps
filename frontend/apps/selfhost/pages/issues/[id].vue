<script setup lang="ts">
import { cn } from '@gwei/core/utils/cn'
import Badge from '@gwei/core/components/ui/Badge.vue'
import Button from '@gwei/core/components/ui/Button.vue'
import Timeline from '@gwei/core/components/Timeline.vue'
import CanaryProgress from '@gwei/core/components/CanaryProgress.vue'
import { useIssueDetail } from '@gwei/core/composables/useIssueDetail'

const route = useRoute()
const id = route.params.id as string
const { data: issue, loading: isLoading } = useIssueDetail(id)

const severityColors: Record<string, string> = {
  critical: 'bg-red-500/15 text-red-500',
  medium: 'bg-yellow-500/15 text-yellow-500',
  low: 'bg-green-500/15 text-green-500',
}

const riskColors: Record<string, string> = {
  low: 'text-green-500',
  medium: 'text-yellow-500',
  high: 'text-red-500',
}

const typeLabels: Record<string, string> = {
  hotfix: '快速修复',
  proper: '根因修复',
  refactor: '架构重构',
  upstream: '上游更新',
  patch: '应急补丁',
  docs: '文档修复',
}
</script>

<template>
  <div v-if="isLoading || !issue" class="space-y-6">
    <div class="h-8 w-64 bg-muted rounded animate-pulse" />
    <div class="h-12 bg-card border border-border rounded-lg animate-pulse" />
    <div class="grid grid-cols-3 gap-px bg-border rounded-lg overflow-hidden">
      <div v-for="i in 3" :key="i" class="h-48 bg-card animate-pulse" />
    </div>
  </div>

  <div v-else class="space-y-6 max-w-4xl">
    <!-- Header -->
    <div class="flex items-start justify-between pb-5 border-b border-border">
      <div>
        <h1 class="text-xl font-bold tracking-tight mb-2">{{ issue.title }}</h1>
        <div class="flex items-center gap-3 text-xs text-muted-foreground">
          <Badge variant="secondary" :class="severityColors[issue.severity]">
            {{ issue.severity === 'critical' ? '紧急' : issue.severity === 'medium' ? '中等' : '低风险' }}
          </Badge>
          <span>来源: {{ issue.source }}</span>
          <span>仓库: {{ issue.repo }}</span>
          <span>{{ issue.triggeredAt }} 触发</span>
        </div>
      </div>
      <div class="flex items-center gap-2">
        <Button variant="outline" size="sm" class="text-red-500 border-red-500/30">回滚</Button>
        <Button variant="outline" size="sm">退回重新诊断</Button>
        <Button size="sm">采纳方案</Button>
      </div>
    </div>

    <!-- Timeline -->
    <Timeline :steps="issue.timeline" />

    <!-- Patches comparison -->
    <div>
      <h2 class="text-sm font-semibold mb-3">修复方案对比</h2>
      <div class="grid grid-cols-1 md:grid-cols-3 gap-px bg-border rounded-lg overflow-hidden">
        <div
          v-for="patch in issue.patches"
          :key="patch.id"
          :class="cn('bg-card p-4 flex flex-col', patch.selected && 'ring-2 ring-primary ring-inset')"
        >
          <div :class="cn(
            'text-[11px] font-bold uppercase tracking-wider mb-2',
            patch.type === 'hotfix' && 'text-red-500',
            patch.type === 'proper' && 'text-blue-500',
            patch.type === 'refactor' && 'text-green-500',
            patch.type === 'upstream' && 'text-blue-500',
            patch.type === 'patch' && 'text-yellow-500',
            patch.type === 'docs' && 'text-green-500'
          )">
            {{ typeLabels[patch.type] ?? patch.type }}
          </div>
          <p class="text-xs text-muted-foreground mb-3 flex-1">{{ patch.description }}</p>
          <div class="grid grid-cols-2 gap-2 text-[11px]">
            <div>
              <div class="text-muted-foreground">风险</div>
              <div :class="cn('font-semibold', riskColors[patch.risk])">
                {{ patch.risk === 'low' ? '低' : patch.risk === 'medium' ? '中' : '高' }}
              </div>
            </div>
            <div>
              <div class="text-muted-foreground">改动</div>
              <div class="font-semibold">{{ patch.lines }} 行</div>
            </div>
            <div>
              <div class="text-muted-foreground">通过率</div>
              <div class="font-semibold text-green-500">{{ patch.passRate }}%</div>
            </div>
            <div>
              <div class="text-muted-foreground">延迟影响</div>
              <div class="font-semibold">{{ patch.latency }}</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Canary Progress -->
    <div v-if="issue.canary" class="bg-card border border-border rounded-lg p-4">
      <h2 class="text-sm font-semibold mb-3">金丝雀验证进度</h2>
      <CanaryProgress
        :steps="issue.canary.steps"
        :completed-steps="issue.canary.completedSteps"
        :current-step="issue.canary.current"
        :metrics="issue.canary.metrics"
      />
    </div>
  </div>
</template>
