'use client'

import { useParams } from 'next/navigation'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Timeline } from '@/components/timeline'
import { CanaryProgress } from '@/components/canary-progress'
import { EmptyState } from '@/components/empty-state'
import { useIssue } from '@/features/issues/hooks'
import { cn } from '@/lib/utils'

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

export default function IssueDetailPage() {
  const params = useParams()
  const { data: issue, isLoading } = useIssue(params.id as string)

  if (isLoading || !issue) {
    return (
      <div className="space-y-6">
        <div className="h-8 w-64 bg-muted rounded animate-pulse" />
        <div className="h-12 bg-card border border-border rounded-lg animate-pulse" />
        <div className="grid grid-cols-3 gap-px bg-border rounded-lg overflow-hidden">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="h-48 bg-card animate-pulse" />
          ))}
        </div>
      </div>
    )
  }

  const selectedPatch = issue.patches.find(p => p.selected) ?? issue.patches[0]

  return (
    <div className="space-y-6 max-w-4xl">
      {/* Header */}
      <div className="flex items-start justify-between pb-5 border-b border-border">
        <div>
          <h1 className="text-xl font-bold tracking-tight mb-2">{issue.title}</h1>
          <div className="flex items-center gap-3 text-xs text-muted-foreground">
            <Badge variant="secondary" className={severityColors[issue.severity]}>
              {issue.severity === 'critical' ? '紧急' : issue.severity === 'medium' ? '中等' : '低风险'}
            </Badge>
            <span>来源: {issue.source}</span>
            <span>仓库: {issue.repo}</span>
            <span>{issue.triggeredAt} 触发</span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" className="text-red-500 border-red-500/30">回滚</Button>
          <Button variant="outline" size="sm">退回重新诊断</Button>
          <Button size="sm">采纳方案</Button>
        </div>
      </div>

      {/* Timeline */}
      <Timeline steps={issue.timeline} />

      {/* Patches comparison */}
      <div>
        <h2 className="text-sm font-semibold mb-3">修复方案对比</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-px bg-border rounded-lg overflow-hidden">
          {issue.patches.map((patch) => (
            <div key={patch.id} className={cn('bg-card p-4 flex flex-col', patch.selected && 'ring-2 ring-primary ring-inset')}>
              <div className={cn(
                'text-[11px] font-bold uppercase tracking-wider mb-2',
                patch.type === 'hotfix' && 'text-red-500',
                patch.type === 'proper' && 'text-blue-500',
                patch.type === 'refactor' && 'text-green-500',
                patch.type === 'upstream' && 'text-blue-500',
                patch.type === 'patch' && 'text-yellow-500',
                patch.type === 'docs' && 'text-green-500',
              )}>
                {typeLabels[patch.type] ?? patch.type}
              </div>
              <p className="text-xs text-muted-foreground mb-3 flex-1">{patch.description}</p>
              <div className="grid grid-cols-2 gap-2 text-[11px]">
                <div>
                  <div className="text-muted-foreground">风险</div>
                  <div className={cn('font-semibold', riskColors[patch.risk])}>
                    {patch.risk === 'low' ? '低' : patch.risk === 'medium' ? '中' : '高'}
                  </div>
                </div>
                <div>
                  <div className="text-muted-foreground">改动</div>
                  <div className="font-semibold">{patch.lines} 行</div>
                </div>
                <div>
                  <div className="text-muted-foreground">通过率</div>
                  <div className="font-semibold text-green-500">{patch.passRate}%</div>
                </div>
                <div>
                  <div className="text-muted-foreground">延迟影响</div>
                  <div className="font-semibold">{patch.latency}</div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Canary Progress */}
      {issue.canary && (
        <div className="bg-card border border-border rounded-lg p-4">
          <h2 className="text-sm font-semibold mb-3">金丝雀验证进度</h2>
          <CanaryProgress
            steps={issue.canary.steps}
            completedSteps={issue.canary.completedSteps}
            currentStep={issue.canary.current}
            metrics={issue.canary.metrics}
          />
        </div>
      )}
    </div>
  )
}
