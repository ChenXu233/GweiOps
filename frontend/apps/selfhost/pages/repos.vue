<script setup lang="ts">
import { useRepoList } from '@gwei/core/composables/useRepoList'
import StatusDot from '@gwei/core/components/StatusDot.vue'
import Badge from '@gwei/core/components/ui/Badge.vue'
import Button from '@gwei/core/components/ui/Button.vue'
import EmptyState from '@gwei/core/components/EmptyState.vue'

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

const { repos, loading } = useRepoList()
</script>

<template>
  <!-- Skeleton loader -->
  <div v-if="loading" class="space-y-6">
    <div class="flex items-center justify-between">
      <h1 class="text-2xl font-bold tracking-tight">仓库管理</h1>
    </div>
    <div v-for="i in 3" :key="i" class="h-14 bg-card border border-border rounded-lg animate-pulse" />
  </div>

  <!-- Empty state -->
  <div v-else-if="!repos || repos.length === 0" class="space-y-6">
    <h1 class="text-2xl font-bold tracking-tight">仓库管理</h1>
    <EmptyState
      icon="📦"
      title="还没有订阅仓库"
      description="订阅一个 GitHub 仓库，GweiOps 会自动监控 Issue 并生成修复方案。"
      :action="{ label: '订阅第一个仓库', href: '#' }"
    />
  </div>

  <!-- Table -->
  <div v-else class="space-y-6">
    <div class="flex items-center justify-between">
      <h1 class="text-2xl font-bold tracking-tight">仓库管理</h1>
      <Button>+ 订阅新仓库</Button>
    </div>

    <div class="border border-border rounded-lg overflow-hidden">
      <div class="grid grid-cols-[1fr_120px_100px_100px_80px] gap-4 px-4 py-2 bg-muted/50 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        <div>仓库</div>
        <div>状态</div>
        <div>Issues</div>
        <div>Agent</div>
        <div>操作</div>
      </div>
      <div
        v-for="repo in repos"
        :key="repo.id"
        class="grid grid-cols-[1fr_120px_100px_100px_80px] gap-4 px-4 py-3 border-t border-border items-center"
      >
        <div class="flex items-center gap-3">
          <span class="text-base">{{ repo.icon }}</span>
          <span class="text-sm font-medium">{{ repo.name }}</span>
        </div>
        <div class="flex items-center gap-2">
          <StatusDot :status="statusDotColors[repo.status]" />
          <span class="text-xs">{{ statusLabels[repo.status] }}</span>
        </div>
        <div class="text-sm">{{ repo.issueCount }} 个</div>
        <div>
          <Badge v-if="repo.activeAgents > 0" variant="secondary" class="bg-green-500/15 text-green-500 text-[10px]">
            {{ repo.activeAgents }} 活跃
          </Badge>
          <span v-else class="text-xs text-muted-foreground">—</span>
        </div>
        <div>
          <Button class="bg-transparent hover:bg-accent hover:text-accent-foreground text-xs h-7 px-2">配置</Button>
        </div>
      </div>
    </div>
  </div>
</template>
