<script setup lang="ts">
import { useRepoList } from '@gwei/core/composables/useRepoList'
import { useWorkspaces } from '@gwei/core/composables/useWorkspaces'

const { repos, loading, error, refresh } = useRepoList()
// 仓库属于一个工作区:同一个仓库名在别的平台上不是同一份代码,所以列表上带来源。
const { current } = useWorkspaces()

const sourceLabel: Record<string, string> = {
  github: 'GitHub',
  cnb: 'CNB',
  gitlab: 'GitLab',
}

const statusTone: Record<string, 'ok' | 'warn' | 'idle'> = {
  running: 'ok',
  configuring: 'warn',
  paused: 'idle',
}

const statusLabel: Record<string, string> = {
  running: '在跑',
  configuring: '配置中',
  paused: '已暂停',
}

const statusChip: Record<string, string> = {
  running: 'chip-ok',
  configuring: 'chip-warn',
  paused: '',
}
</script>

<template>
  <div class="space-y-5">
    <PageHeader
      eyebrow="REPOSITORIES"
      title="仓库"
      :description="`${current?.name ?? '当前工作区'}里引擎订阅的仓库，以及它当前盯着的执行体数量。`"
    >
      <template #actions>
        <button class="btn-outline btn-sm" :disabled="loading" @click="refresh">
          <AppIcon name="refresh" :size="13" :class="loading ? 'animate-spin' : ''" />
          刷新
        </button>
      </template>
    </PageHeader>

    <div v-if="error" class="panel border-coral/30 bg-coral/5 p-4 text-[12.5px] text-coral">
      拉不到仓库列表。确认引擎在跑，或开启 mock 模式。
    </div>

    <div v-if="loading && !repos.length" class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <div v-for="i in 6" :key="i" class="h-[186px] skeleton" />
    </div>

    <EmptyState
      v-else-if="!repos.length"
      icon="repos"
      title="还没有接入仓库"
      hint="装一个来源适配器后，把仓库绑定到当前工作区。"
    />

    <div v-else class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <article
        v-for="repo in repos"
        :key="repo.id"
        class="panel panel-lift flex flex-col p-5"
      >
        <div class="flex items-start justify-between gap-3">
          <span
            class="grid h-9 w-9 place-items-center rounded-tile bg-well text-ink-soft transition-colors duration-200 ease-[var(--ease)] group-hover:bg-ink group-hover:text-paper"
          >
            <AppIcon name="repos" :size="16" />
          </span>
          <StatusPip :tone="statusTone[repo.status]" :label="statusLabel[repo.status]" />
        </div>

        <div class="mt-4 flex items-baseline gap-2">
          <h2 class="min-w-0 break-all font-mono text-[13px] font-medium leading-snug">{{ repo.name }}</h2>
          <span class="shrink-0 rounded-md bg-well px-1.5 py-0.5 text-[10.5px] text-ink-faint">
            {{ sourceLabel[repo.source] ?? repo.source }}
          </span>
        </div>

        <div class="mt-auto grid grid-cols-2 gap-3 border-t border-line/70 pt-3.5">
          <div>
            <div class="eyebrow">议题</div>
            <div class="num mt-1 text-[15px] font-semibold">{{ repo.issueCount }}</div>
          </div>
          <div>
            <div class="eyebrow">执行体</div>
            <div class="num mt-1 text-[15px] font-semibold">{{ repo.activeAgents }}</div>
          </div>
        </div>

        <div class="mt-3 font-mono text-[11.5px] text-ink-faint">同步于 {{ repo.lastSyncAt }}</div>
      </article>
    </div>
  </div>
</template>