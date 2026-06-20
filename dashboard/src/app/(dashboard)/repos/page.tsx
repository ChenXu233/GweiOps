'use client'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/empty-state'
import { useRepos } from '@/features/repos/hooks'
import { StatusDot } from '@/components/status-dot'

const statusLabels: Record<string, string> = {
  running: '运行中',
  configuring: '待配置',
  paused: '已暂停',
}

const statusDotColors: Record<string, 'healthy' | 'warning' | 'critical'> = {
  running: 'healthy',
  configuring: 'warning',
  paused: 'critical',
}

export default function ReposPage() {
  const { data: repos, isLoading } = useRepos()

  if (isLoading) {
    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold tracking-tight">仓库管理</h1>
        </div>
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="h-14 bg-card border border-border rounded-lg animate-pulse" />
        ))}
      </div>
    )
  }

  if (!repos || repos.length === 0) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold tracking-tight">仓库管理</h1>
        <EmptyState icon="📦" title="还没有订阅仓库" description="订阅一个 GitHub 仓库，GweiOps 会自动监控 Issue 并生成修复方案。" action={{ label: '订阅第一个仓库', href: '#' }} />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold tracking-tight">仓库管理</h1>
        <Button>+ 订阅新仓库</Button>
      </div>

      <div className="border border-border rounded-lg overflow-hidden">
        <div className="grid grid-cols-[1fr_120px_100px_100px_80px] gap-4 px-4 py-2 bg-muted/50 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          <div>仓库</div>
          <div>状态</div>
          <div>Issues</div>
          <div>Agent</div>
          <div>操作</div>
        </div>
        {repos.map((repo) => (
          <div key={repo.id} className="grid grid-cols-[1fr_120px_100px_100px_80px] gap-4 px-4 py-3 border-t border-border items-center">
            <div className="flex items-center gap-3">
              <span className="text-base">{repo.icon}</span>
              <span className="text-sm font-medium">{repo.name}</span>
            </div>
            <div className="flex items-center gap-2">
              <StatusDot status={statusDotColors[repo.status]} />
              <span className="text-xs">{statusLabels[repo.status]}</span>
            </div>
            <div className="text-sm">{repo.issueCount} 个</div>
            <div>
              {repo.activeAgents > 0 ? (
                <Badge variant="secondary" className="bg-green-500/15 text-green-500 text-[10px]">
                  {repo.activeAgents} 活跃
                </Badge>
              ) : (
                <span className="text-xs text-muted-foreground">—</span>
              )}
            </div>
            <div>
              <Button variant="ghost" size="sm" className="text-xs h-7">配置</Button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
