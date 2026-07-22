<script setup lang="ts">
import { computed } from 'vue'
import { useDashboard } from '@gwei/core/composables/useDashboard'
import BentoGrid from '@gwei/core/components/BentoGrid.vue'
import BentoCell from '@gwei/core/components/BentoCell.vue'
import StatusDot from '@gwei/core/components/StatusDot.vue'
import MetricCard from '@gwei/core/components/MetricCard.vue'
import CanaryProgress from '@gwei/core/components/CanaryProgress.vue'
import EmptyState from '@gwei/core/components/EmptyState.vue'
import Badge from '@gwei/core/components/ui/Badge.vue'

const severityColors = {
  critical: 'bg-red-500/15 text-red-500',
  medium: 'bg-yellow-500/15 text-yellow-500',
  low: 'bg-green-500/15 text-green-500',
}

const { data: dashboard, pendingIssues, overnightEvents, canaryStatuses, loading } = useDashboard()

const canary = computed(() => canaryStatuses.value[0])

const pendingSub = computed(() => {
  const criticalCount = pendingIssues.value.filter(i => i.severity === 'critical').length
  const otherCount = pendingIssues.value.filter(i => i.severity !== 'critical').length
  return `${criticalCount} 紧急 · ${otherCount} 其他`
})

const canaryCompletedSteps = computed(() => {
  if (!canary.value) return []
  const idx = canary.value.steps.indexOf(canary.value.currentStep)
  return canary.value.steps.slice(0, idx)
})

function severityLabel(severity: string): string {
  if (severity === 'critical') return '紧急'
  if (severity === 'medium') return '中等'
  return '低风险'
}

function statusLabel(status: string): string {
  if (status === 'healthy') return '系统正常运行'
  if (status === 'warning') return '有告警处理中'
  return '有紧急事件'
}
</script>

<template>
  <div v-if="loading || !dashboard" class="space-y-6">
    <div class="h-8 w-32 bg-muted rounded animate-pulse" />
    <BentoGrid>
      <BentoCell :span="2">
        <div class="h-4 w-24 bg-muted rounded animate-pulse mb-3" />
        <div class="h-6 w-48 bg-muted rounded animate-pulse mb-2" />
        <div class="h-3 w-64 bg-muted rounded animate-pulse mb-3" />
        <div class="flex gap-0.5">
          <div v-for="i in 10" :key="i" class="h-1 flex-1 bg-muted rounded-full animate-pulse" />
        </div>
      </BentoCell>
      <BentoCell>
        <div class="h-3 w-16 bg-muted rounded animate-pulse mb-2" />
        <div class="h-8 w-12 bg-muted rounded animate-pulse" />
      </BentoCell>
      <BentoCell>
        <div class="h-3 w-20 bg-muted rounded animate-pulse mb-2" />
        <div class="h-8 w-12 bg-muted rounded animate-pulse" />
      </BentoCell>
      <BentoCell :span="3">
        <div class="h-4 w-24 bg-muted rounded animate-pulse mb-3" />
        <div v-for="i in 3" :key="i" class="h-10 bg-muted rounded animate-pulse mb-2" />
      </BentoCell>
      <BentoCell>
        <div class="h-4 w-24 bg-muted rounded animate-pulse mb-3" />
        <div class="h-8 w-16 bg-muted rounded animate-pulse" />
      </BentoCell>
      <BentoCell :span="4">
        <div class="h-4 w-24 bg-muted rounded animate-pulse mb-3" />
        <div class="h-6 w-full bg-muted rounded animate-pulse" />
      </BentoCell>
    </BentoGrid>
  </div>

  <div v-else class="space-y-6">
    <h1 class="text-2xl font-bold tracking-tight">态势感知</h1>

    <BentoGrid>
      <!-- 整体态势 -->
      <BentoCell :span="2">
        <div class="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-3">
          整体态势
        </div>
        <div class="flex items-center gap-2 mb-2">
          <StatusDot :status="dashboard!.status" size="md" />
          <span class="text-lg font-semibold">
            {{ statusLabel(dashboard!.status) }}
          </span>
        </div>
        <div class="text-xs text-muted-foreground mb-3">
          连续 {{ dashboard!.consecutiveDays }} 天无故障 · 上次事故 {{ dashboard!.lastIncident }}
        </div>
        <div class="flex gap-0.5">
          <div
            v-for="(ok, i) in dashboard!.healthHistory"
            :key="i"
            :class="['h-1 flex-1 rounded-full', ok ? 'bg-green-500' : 'bg-yellow-500']"
          />
        </div>
      </BentoCell>

      <!-- 待审 -->
      <BentoCell>
        <MetricCard
          label="待审"
          :value="dashboard!.pendingReview"
          :sub="pendingSub"
          variant="yellow"
        />
      </BentoCell>

      <!-- 昨夜修复 -->
      <BentoCell>
        <MetricCard
          label="昨夜修复"
          :value="dashboard!.overnightFixed"
          sub="全部自动完成"
          variant="green"
        />
      </BentoCell>

      <!-- 待审案件 -->
      <BentoCell :span="3">
        <div class="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-3">
          待审案件
        </div>
        <div v-if="pendingIssues.length > 0" class="space-y-0">
          <div
            v-for="issue in pendingIssues"
            :key="issue.id"
            class="flex items-center justify-between py-2.5 border-b border-border last:border-0"
          >
            <div class="flex items-center gap-3">
              <span class="text-xs text-muted-foreground font-mono">{{ issue.id }}</span>
              <span class="text-sm">{{ issue.title }}</span>
            </div>
            <div class="flex items-center gap-2">
              <Badge variant="secondary" :class="severityColors[issue.severity]">
                {{ severityLabel(issue.severity) }}
              </Badge>
              <Badge variant="secondary" class="bg-blue-500/15 text-blue-500">
                {{ issue.patchCount }} 方案
              </Badge>
            </div>
          </div>
        </div>
        <EmptyState
          v-else
          icon="☕"
          title="昨夜平安无事"
          description="没有告警触发，GweiOps 什么都没做。这其实是最好的消息。"
        />
      </BentoCell>

      <!-- 系统健康 -->
      <BentoCell>
        <div class="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-3">
          系统健康
        </div>
        <div class="space-y-4">
          <MetricCard label="" :value="`${dashboard!.successRate}%`" sub="成功率（7日）" variant="green" />
          <MetricCard label="" :value="dashboard!.mttr" suffix="min" sub="平均修复时间" />
          <MetricCard label="" :value="dashboard!.activeAgents" sub="活跃 Agent" />
          <div v-if="canary">
            <div class="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-2">
              金丝雀进度
            </div>
            <div class="text-xs mb-1">{{ canary.issueTitle }}</div>
            <CanaryProgress
              :steps="canary.steps"
              :completed-steps="canaryCompletedSteps"
              :current-step="canary.currentStep"
              :metrics="canary.metrics"
            />
          </div>
        </div>
      </BentoCell>

      <!-- 昨夜回顾 -->
      <BentoCell :span="4">
        <div class="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-3">
          昨夜回顾
        </div>
        <div v-if="overnightEvents.length > 0" class="flex gap-6 overflow-x-auto">
          <div
            v-for="(event, i) in overnightEvents"
            :key="i"
            class="flex items-start gap-3 min-w-0"
          >
            <span class="text-xs text-muted-foreground font-mono whitespace-nowrap">{{ event.time }}</span>
            <div class="h-1.5 w-1.5 rounded-full bg-green-500 mt-1.5 flex-shrink-0" />
            <div class="min-w-0">
              <div class="text-sm font-medium">{{ event.title }}</div>
              <div class="text-xs text-muted-foreground truncate">{{ event.description }}</div>
            </div>
          </div>
        </div>
        <EmptyState
          v-else
          icon="🌙"
          title="夜间无事件"
          description="一切平静，GweiOps 在安静守护。"
        />
      </BentoCell>
    </BentoGrid>
  </div>
</template>
