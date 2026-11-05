<script setup lang="ts">
import { useIssueList } from '@gwei/core/composables/useIssueList'
import type { IssueStatus } from '@gwei/core/types/issues'

const { data, loading, error, refresh } = useIssueList()
const filter = ref<'all' | IssueStatus>('all')

const statusLabel: Record<string, string> = {
  pending_review: '待审',
  canary: '金丝雀',
  approved: '已放行',
  completed: '已完成',
  rolled_back: '已回滚',
}

const statusCls: Record<string, string> = {
  pending_review: 'chip-warn',
  canary: 'chip-info',
  approved: 'chip-ok',
  completed: 'chip-ok',
  rolled_back: '',
}

const sourceLabel: Record<string, string> = {
  github_issue: 'GitHub',
  prometheus: 'Prometheus',
  trivy: 'Trivy',
  cve: 'CVE',
  sentry: 'Sentry',
}

const severityLabel: Record<string, string> = {
  critical: '严重',
  medium: '中等',
  low: '轻微',
}

function severityBar(severity: string) {
  if (severity === 'critical') return 'bg-coral'
  if (severity === 'medium') return 'bg-amber'
  return 'bg-ink-faint'
}

const counts = computed(() => {
  const c: Record<string, number> = {}
  for (const i of data.value) c[i.status] = (c[i.status] ?? 0) + 1
  return c
})

const visible = computed(() =>
  filter.value === 'all' ? data.value : data.value.filter(i => i.status === filter.value),
)

const filters: { key: 'all' | IssueStatus; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'pending_review', label: '待审' },
  { key: 'canary', label: '金丝雀' },
  { key: 'completed', label: '已完成' },
  { key: 'rolled_back', label: '已回滚' },
]
</script>

<template>
  <div class="space-y-4">
    <PageHeader eyebrow="ISSUES" title="议题" description="从信号到方案，每一步都留痕。">
      <template #actions>
        <span class="eyebrow">{{ data.length }} 条</span>
        <button class="btn-outline btn-sm" :disabled="loading" @click="refresh">
          <AppIcon name="refresh" :size="13" :class="loading ? 'animate-spin' : ''" />
          刷新
        </button>
      </template>
    </PageHeader>

    <div class="no-scrollbar flex items-center gap-1 overflow-x-auto pb-1">
      <button
        v-for="f in filters"
        :key="f.key"
        class="tab"
        :class="filter === f.key ? 'tab-active' : ''"
        @click="filter = f.key"
      >
        {{ f.label }}
        <span class="num font-mono text-[10px] opacity-60">
          {{ f.key === 'all' ? data.length : counts[f.key] ?? 0 }}
        </span>
      </button>
    </div>

    <div v-if="error" class="panel border-coral/30 bg-coral/5 p-4 text-[12.5px] text-coral">
      拉不到议题列表。确认引擎在跑,或开启 mock 模式。
    </div>

    <div class="panel overflow-hidden">
      <div v-if="loading && !data.length" class="divide-y divide-line/60">
        <div v-for="i in 5" :key="i" class="h-[72px] animate-pulse bg-well/50" />
      </div>

      <EmptyState
        v-else-if="!visible.length"
        icon="inbox"
        title="这个分类下没有议题"
        hint="信号进来之后,它会自动被诊断、出方案、跑验证。"
      />

      <ul v-else class="divide-y divide-line/60">
        <li v-for="issue in visible" :key="issue.id">
          <NuxtLink
            :to="'/issues/' + encodeURIComponent(issue.id)"
            class="group flex items-center gap-4 px-5 py-4 transition-colors hover:bg-well/40"
          >
            <span class="h-9 w-[3px] shrink-0 rounded-full" :class="severityBar(issue.severity)" />

            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-2">
                <span class="truncate text-[13.5px] font-medium">{{ issue.title }}</span>
                <span class="shrink-0 font-mono text-[10.5px] text-ink-faint">{{ issue.id }}</span>
              </div>
              <div class="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[10.5px] text-ink-faint">
                <span>{{ issue.repo }}</span>
                <span class="h-1 w-1 rounded-full bg-line" />
                <span>{{ sourceLabel[issue.source] || issue.source }}</span>
                <span class="h-1 w-1 rounded-full bg-line" />
                <span>{{ issue.triggeredAt }}</span>
                <span class="h-1 w-1 rounded-full bg-line" />
                <span>{{ severityLabel[issue.severity] }}</span>
              </div>
            </div>

            <span class="chip hidden shrink-0 font-mono text-[10.5px] sm:inline">
              {{ issue.patches.length }} 方案
            </span>

            <span class="chip shrink-0" :class="statusCls[issue.status]">
              {{ statusLabel[issue.status] }}
            </span>

            <AppIcon
              name="chevron-right"
              :size="14"
              class="shrink-0 text-ink-faint opacity-0 transition-opacity group-hover:opacity-100"
            />
          </NuxtLink>
        </li>
      </ul>
    </div>
  </div>
</template>
