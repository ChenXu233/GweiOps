<script setup lang="ts">
import EmptyState from '@gwei/core/components/EmptyState.vue'
import { useChanges } from '@gwei/core/composables/useChanges'

const verdictLabels: Record<string, string> = {
  kept: '已执行 · 可撤',
  rolled_back: '已回滚',
  blocked: '阻断等人',
  vetoed: '被否决',
  irreversible: '不可逆',
  pending: '进行中',
}

const verdictColors: Record<string, string> = {
  kept: 'bg-green-500/15 text-green-500',
  rolled_back: 'bg-muted text-muted-foreground',
  blocked: 'bg-yellow-500/15 text-yellow-500',
  vetoed: 'bg-yellow-500/15 text-yellow-500',
  irreversible: 'bg-red-500/15 text-red-500',
  pending: 'bg-blue-500/15 text-blue-500',
}

const { items, loading, error, rollingBack, refresh, rollback } = useChanges()

function canRollback(row: { handle: string | null, verdict: string }) {
  return Boolean(row.handle) && row.verdict === 'kept'
}

function when(iso: string) {
  return iso ? iso.slice(0, 19).replace('T', ' ') : ''
}

async function onRollback(row: { id: string, intent?: { summary?: string } }) {
  if (!window.confirm('撤销这次变更？撤销本身也会记进账本。'))
    return
  await rollback(row.id)
}
</script>

<template>
  <div class="space-y-6">
    <div class="flex items-end justify-between">
      <div>
        <h1 class="text-2xl font-bold tracking-tight">变更账本</h1>
        <p class="text-sm text-muted-foreground mt-1">
          夜里发生了什么。每一行都是一次可追溯的外部改变，可撤销。
        </p>
      </div>
      <button
        class="text-sm px-3 py-1.5 border border-border rounded-md hover:bg-muted/40"
        :disabled="loading"
        @click="refresh()"
      >
        刷新
      </button>
    </div>

    <div v-if="error" class="text-sm text-red-500 border border-red-500/30 rounded-md px-3 py-2">
      {{ error }}
    </div>

    <div v-if="loading" class="space-y-3">
      <div v-for="i in 3" :key="i" class="h-14 bg-card border border-border rounded-lg animate-pulse" />
    </div>

    <EmptyState
      v-else-if="items.length === 0"
      icon="📘"
      title="账本还是空的"
      description="还没有任何效果被执行过。第一次自动回评之后，这里会出现第一行。"
    />

    <div v-else class="border border-border rounded-lg overflow-hidden">
      <div class="grid grid-cols-[150px_1.4fr_90px_120px_1.6fr_90px] gap-3 px-4 py-2 bg-muted/50 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        <div>时间</div>
        <div>意图</div>
        <div>目标</div>
        <div>结论</div>
        <div>说明</div>
        <div class="text-right">操作</div>
      </div>
      <div
        v-for="row in items"
        :key="row.id"
        class="grid grid-cols-[150px_1.4fr_90px_120px_1.6fr_90px] gap-3 px-4 py-3 border-t border-border items-center"
      >
        <div class="text-xs font-mono text-muted-foreground">{{ when(row.created_at) }}</div>
        <div class="text-sm truncate" :title="row.intent?.summary">
          {{ row.intent?.summary || row.effect?.capability || '—' }}
        </div>
        <div class="text-xs font-mono text-muted-foreground">{{ row.binding || '—' }}</div>
        <div>
          <span class="text-[11px] px-2 py-0.5 rounded-full" :class="verdictColors[row.verdict] || 'bg-muted'">
            {{ verdictLabels[row.verdict] || row.verdict }}
          </span>
        </div>
        <div class="text-xs text-muted-foreground truncate" :title="row.reason">{{ row.reason }}</div>
        <div class="text-right">
          <button
            v-if="canRollback(row)"
            class="text-xs px-2.5 py-1 border border-border rounded-md hover:bg-red-500/10 hover:text-red-500 disabled:opacity-50"
            :disabled="rollingBack === row.id"
            @click="onRollback(row)"
          >
            {{ rollingBack === row.id ? '撤销中…' : '撤销' }}
          </button>
          <span v-else class="text-xs text-muted-foreground">—</span>
        </div>
      </div>
    </div>
  </div>
</template>
