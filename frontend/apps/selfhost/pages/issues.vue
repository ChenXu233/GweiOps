<script setup lang="ts">
import Badge from '@gwei/core/components/ui/Badge.vue'
import EmptyState from '@gwei/core/components/EmptyState.vue'
import { useIssueList } from '@gwei/core/composables/useIssueList'

const severityColors: Record<string, string> = {
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

const { data: issues, loading: isLoading } = useIssueList()
</script>

<template>
  <div class="space-y-6">
    <h1 class="text-2xl font-bold tracking-tight">Issues</h1>

    <!-- Skeleton -->
    <div v-if="isLoading" class="space-y-4">
      <div
        v-for="i in 3"
        :key="i"
        class="h-16 bg-card border border-border rounded-lg animate-pulse"
      />
    </div>

    <!-- Empty -->
    <EmptyState
      v-else-if="!issues || issues.length === 0"
      icon="✨"
      title="一切正常，没有待审案件"
      description="GweiOps 正在后台守护你的仓库。有问题时会第一时间出现。"
    />

    <!-- Table -->
    <div v-else class="border border-border rounded-lg overflow-hidden">
      <div class="grid grid-cols-[100px_1fr_120px_100px_80px] gap-4 px-4 py-2 bg-muted/50 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        <div>ID</div>
        <div>标题</div>
        <div>来源</div>
        <div>严重程度</div>
        <div>状态</div>
      </div>
      <NuxtLink
        v-for="issue in issues"
        :key="issue.id"
        :to="`/issues/${issue.id}`"
        class="grid grid-cols-[100px_1fr_120px_100px_80px] gap-4 px-4 py-3 border-t border-border hover:bg-muted/30 transition-colors"
      >
        <div class="text-sm font-mono text-muted-foreground">{{ issue.id }}</div>
        <div class="text-sm truncate">{{ issue.title }}</div>
        <div class="text-xs text-muted-foreground">{{ issue.source }}</div>
        <div>
          <Badge variant="secondary" :class="severityColors[issue.severity]">
            {{ issue.severity === 'critical' ? '紧急' : issue.severity === 'medium' ? '中等' : '低' }}
          </Badge>
        </div>
        <div class="text-xs text-muted-foreground">{{ statusLabels[issue.status] ?? issue.status }}</div>
      </NuxtLink>
    </div>
  </div>
</template>
