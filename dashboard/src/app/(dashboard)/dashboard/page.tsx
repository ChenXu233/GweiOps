'use client'

import { BentoGrid, BentoCell } from '@/components/bento-grid'
import { StatusDot } from '@/components/status-dot'
import { MetricCard } from '@/components/metric-card'
import { CanaryProgress } from '@/components/canary-progress'
import { EmptyState } from '@/components/empty-state'
import { Badge } from '@/components/ui/badge'
import { useDashboardData, usePendingIssues, useOvernightEvents, useCanaryStatuses } from '@/features/dashboard/hooks'

const severityColors = {
  critical: 'bg-red-500/15 text-red-500',
  medium: 'bg-yellow-500/15 text-yellow-500',
  low: 'bg-green-500/15 text-green-500',
}

export default function DashboardPage() {
  const { data: dashboard, isLoading: dashboardLoading } = useDashboardData()
  const { data: pendingIssues, isLoading: pendingLoading } = usePendingIssues()
  const { data: overnightEvents, isLoading: overnightLoading } = useOvernightEvents()
  const { data: canaryStatuses } = useCanaryStatuses()

  if (dashboardLoading || !dashboard) {
    return <DashboardSkeleton />
  }

  const canary = canaryStatuses?.[0]

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold tracking-tight">态势感知</h1>

      <BentoGrid>
        {/* Overall status - wide */}
        <BentoCell span={2}>
          <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-3">
            整体态势
          </div>
          <div className="flex items-center gap-2 mb-2">
            <StatusDot status={dashboard.status} size="md" />
            <span className="text-lg font-semibold">
              {dashboard.status === 'healthy' && '系统正常运行'}
              {dashboard.status === 'warning' && '有告警处理中'}
              {dashboard.status === 'critical' && '有紧急事件'}
            </span>
          </div>
          <div className="text-xs text-muted-foreground mb-3">
            连续 {dashboard.consecutiveDays} 天无故障 · 上次事故 {dashboard.lastIncident}
          </div>
          <div className="flex gap-0.5">
            {dashboard.healthHistory.map((ok, i) => (
              <div key={i} className={`h-1 flex-1 rounded-full ${ok ? 'bg-green-500' : 'bg-yellow-500'}`} />
            ))}
          </div>
        </BentoCell>

        {/* Pending review count */}
        <BentoCell>
          <MetricCard
            label="待审"
            value={dashboard.pendingReview}
            sub={`${pendingIssues?.filter(i => i.severity === 'critical').length ?? 0} 紧急 · ${pendingIssues?.filter(i => i.severity !== 'critical').length ?? 0} 其他`}
            variant="yellow"
          />
        </BentoCell>

        {/* Overnight fixes */}
        <BentoCell>
          <MetricCard
            label="昨夜修复"
            value={dashboard.overnightFixed}
            sub="全部自动完成"
            variant="green"
          />
        </BentoCell>

        {/* Pending issues list */}
        <BentoCell span={3}>
          <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-3">
            待审案件
          </div>
          {pendingIssues && pendingIssues.length > 0 ? (
            <div className="space-y-0">
              {pendingIssues.map((issue) => (
                <div key={issue.id} className="flex items-center justify-between py-2.5 border-b border-border last:border-0">
                  <div className="flex items-center gap-3">
                    <span className="text-xs text-muted-foreground font-mono">{issue.id}</span>
                    <span className="text-sm">{issue.title}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge variant="secondary" className={severityColors[issue.severity]}>
                      {issue.severity === 'critical' ? '紧急' : issue.severity === 'medium' ? '中等' : '低风险'}
                    </Badge>
                    <Badge variant="secondary" className="bg-blue-500/15 text-blue-500">
                      {issue.patchCount} 方案
                    </Badge>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState icon="☕" title="昨夜平安无事" description="没有告警触发，GweiOps 什么都没做。这其实是最好的消息。" />
          )}
        </BentoCell>

        {/* System health */}
        <BentoCell>
          <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-3">
            系统健康
          </div>
          <div className="space-y-4">
            <MetricCard label="" value={`${dashboard.successRate}%`} sub="成功率（7日）" variant="green" />
            <MetricCard label="" value={dashboard.mttr} suffix="min" sub="平均修复时间" />
            <MetricCard label="" value={dashboard.activeAgents} sub="活跃 Agent" />
            {canary && (
              <div>
                <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-2">
                  金丝雀进度
                </div>
                <div className="text-xs mb-1">{canary.issueTitle}</div>
                <CanaryProgress
                  steps={canary.steps}
                  completedSteps={canary.steps.slice(0, canary.steps.indexOf(canary.currentStep))}
                  currentStep={canary.currentStep}
                  metrics={canary.metrics}
                />
              </div>
            )}
          </div>
        </BentoCell>

        {/* Overnight review timeline */}
        <BentoCell span={4}>
          <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-3">
            昨夜回顾
          </div>
          {overnightEvents && overnightEvents.length > 0 ? (
            <div className="flex gap-6 overflow-x-auto">
              {overnightEvents.map((event, i) => (
                <div key={i} className="flex items-start gap-3 min-w-0">
                  <span className="text-xs text-muted-foreground font-mono whitespace-nowrap">{event.time}</span>
                  <div className="h-1.5 w-1.5 rounded-full bg-green-500 mt-1.5 flex-shrink-0" />
                  <div className="min-w-0">
                    <div className="text-sm font-medium">{event.title}</div>
                    <div className="text-xs text-muted-foreground truncate">{event.description}</div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState icon="🌙" title="夜间无事件" description="一切平静，GweiOps 在安静守护。" />
          )}
        </BentoCell>
      </BentoGrid>
    </div>
  )
}

function DashboardSkeleton() {
  return (
    <div className="space-y-6">
      <div className="h-8 w-32 bg-muted rounded animate-pulse" />
      <BentoGrid>
        <BentoCell span={2}>
          <div className="h-4 w-24 bg-muted rounded animate-pulse mb-3" />
          <div className="h-6 w-48 bg-muted rounded animate-pulse mb-2" />
          <div className="h-3 w-64 bg-muted rounded animate-pulse mb-3" />
          <div className="flex gap-0.5">
            {Array.from({ length: 10 }).map((_, i) => (
              <div key={i} className="h-1 flex-1 bg-muted rounded-full animate-pulse" />
            ))}
          </div>
        </BentoCell>
        <BentoCell>
          <div className="h-3 w-16 bg-muted rounded animate-pulse mb-2" />
          <div className="h-8 w-12 bg-muted rounded animate-pulse" />
        </BentoCell>
        <BentoCell>
          <div className="h-3 w-20 bg-muted rounded animate-pulse mb-2" />
          <div className="h-8 w-12 bg-muted rounded animate-pulse" />
        </BentoCell>
        <BentoCell span={3}>
          <div className="h-4 w-24 bg-muted rounded animate-pulse mb-3" />
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="h-10 bg-muted rounded animate-pulse mb-2" />
          ))}
        </BentoCell>
        <BentoCell>
          <div className="h-4 w-24 bg-muted rounded animate-pulse mb-3" />
          <div className="h-8 w-16 bg-muted rounded animate-pulse" />
        </BentoCell>
        <BentoCell span={4}>
          <div className="h-4 w-24 bg-muted rounded animate-pulse mb-3" />
          <div className="h-6 w-full bg-muted rounded animate-pulse" />
        </BentoCell>
      </BentoGrid>
    </div>
  )
}
