'use client'

import Link from 'next/link'
import { Badge } from '@/components/ui/badge'
import { EmptyState } from '@/components/empty-state'
import { useIssues } from '@/features/issues/hooks'

const severityColors = {
  critical: 'bg-red-500/15 text-red-500',
  medium: 'bg-yellow-500/15 text-yellow-500',
  low: 'bg-green-500/15 text-green-500',
}

const statusLabels: Record<string, string> = {
  pending_review: '待审',
  canary: '金丝雀中',
  approved: '已采纳',
  completed: '已完成',
  rolled_back: '已回滚',
}

export default function IssuesPage() {
  const { data: issues, isLoading } = useIssues()

  if (isLoading) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-bold tracking-tight">Issues</h1>
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="h-16 bg-card border border-border rounded-lg animate-pulse" />
        ))}
      </div>
    )
  }

  if (!issues || issues.length === 0) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold tracking-tight">Issues</h1>
        <EmptyState icon="✨" title="一切正常，没有待审案件" description="GweiOps 正在后台守护你的仓库。有问题时会第一时间出现。" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold tracking-tight">Issues</h1>
      <div className="border border-border rounded-lg overflow-hidden">
        <div className="grid grid-cols-[100px_1fr_120px_100px_80px] gap-4 px-4 py-2 bg-muted/50 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          <div>ID</div>
          <div>标题</div>
          <div>来源</div>
          <div>严重程度</div>
          <div>状态</div>
        </div>
        {issues.map((issue) => (
          <Link
            key={issue.id}
            href={`/issues/${issue.id}`}
            className="grid grid-cols-[100px_1fr_120px_100px_80px] gap-4 px-4 py-3 border-t border-border hover:bg-muted/30 transition-colors"
          >
            <div className="text-sm font-mono text-muted-foreground">{issue.id}</div>
            <div className="text-sm truncate">{issue.title}</div>
            <div className="text-xs text-muted-foreground">{issue.source}</div>
            <div>
              <Badge variant="secondary" className={severityColors[issue.severity]}>
                {issue.severity === 'critical' ? '紧急' : issue.severity === 'medium' ? '中等' : '低'}
              </Badge>
            </div>
            <div className="text-xs text-muted-foreground">{statusLabels[issue.status] ?? issue.status}</div>
          </Link>
        ))}
      </div>
    </div>
  )
}
