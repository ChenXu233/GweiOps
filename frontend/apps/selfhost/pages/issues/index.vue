<script setup lang="ts">
// 议题板:首页就是这张列表。
//
// 一块板子只问一件事:要不要你。要你的在最上面,系统在做的在中间,昨天那些
// 已经落地的在最下面。三个状态由后端判定,页面只负责把它们分开摆。
import { useIssueBoard } from '@gwei/core/composables/useIssueBoard'
import type { IssueCard } from '@gwei/core/types/issues'
import { actionLabel, outcomeChip, since } from '@gwei/core/utils/verdict'

const { data, loading, error, refresh } = useIssueBoard()

const q = ref('')

const sections = [
  {
    key: 'waiting',
    label: '等我',
    dot: 'bg-amber',
    hint: '不做就不动',
    empty: '没有在等你的议题。',
  },
  {
    key: 'running',
    label: '在跑',
    dot: 'bg-brand',
    hint: '没人要等,系统在做',
    empty: '现在没有在跑的执行。',
  },
  {
    key: 'landed',
    label: '落了',
    dot: 'bg-ok',
    hint: '已经有结论',
    empty: '还没有落地的议题。',
  },
] as const

function matches(card: IssueCard) {
  const needle = q.value.trim().toLowerCase()
  if (!needle) return true
  return (
    card.title.toLowerCase().includes(needle) ||
    card.repo.toLowerCase().includes(needle) ||
    String(card.number).includes(needle)
  )
}

const grouped = computed(() => {
  const rows = (data.value?.items ?? []).filter(matches)
  return sections.map((section) => ({
    ...section,
    items: rows.filter((card) => card.state === section.key),
  }))
})

const total = computed(() => grouped.value.reduce((n, s) => n + s.items.length, 0))
const counts = computed(() => data.value?.counts ?? {})
</script>

<template>
  <div class="space-y-5">
    <PageHeader
      eyebrow="BOARD"
      title="议题"
      description="一个议题一条时间线。这里只按「要不要你」分成三段。"
    >
      <template #actions>
        <span class="eyebrow">{{ data?.total ?? 0 }} 个</span>
        <button class="btn-outline btn-sm" :disabled="loading" @click="refresh">
          <AppIcon name="refresh" :size="13" :class="loading ? 'animate-spin' : ''" />
          刷新
        </button>
      </template>
    </PageHeader>

    <!-- 三个数 + 一个筛选框:这里不是仪表盘,只有"要你几件事"值得先看 -->
    <div class="panel flex flex-wrap items-center gap-x-6 gap-y-3 px-5 py-3.5">
      <a
        v-for="s in sections"
        :key="s.key"
        :href="'#' + s.key"
        class="group flex items-center gap-2 transition-opacity hover:opacity-70"
      >
        <span class="dot" :class="s.dot" />
        <span class="text-[12px] text-ink-soft">{{ s.label }}</span>
        <span class="num font-mono text-[17px] font-semibold leading-none">
          {{ counts[s.key] ?? 0 }}
        </span>
      </a>

      <label class="ml-auto flex items-center gap-2">
        <AppIcon name="search" :size="13" class="text-ink-faint" />
        <input v-model="q" class="field h-8 w-[200px] text-[12.5px]" placeholder="搜标题、仓库或编号" />
      </label>
    </div>

    <div v-if="error" class="panel border-coral/30 bg-coral/5 p-4 text-[12.5px] text-coral">
      拉不到议题板。{{ error }}
    </div>

    <div v-if="loading && !data" class="panel space-y-px overflow-hidden">
      <div v-for="i in 6" :key="i" class="h-[64px] animate-pulse bg-well/50" />
    </div>

    <div v-else-if="!total" class="panel p-6">
      <p class="text-[13px] font-medium">{{ q ? '没有匹配的议题' : '还没有议题' }}</p>
      <p class="mt-1 text-[12px] leading-relaxed text-ink-soft">
        {{
          q
            ? '换个词试试,或者清空筛选看全部。'
            : '仓库里来一个 issue、或者外部系统推一条信号,这里就会出现第一条。'
        }}
      </p>
    </div>

    <template v-else>
      <section
        v-for="s in grouped"
        :id="s.key"
        :key="s.key"
        class="panel scroll-mt-4 overflow-hidden"
      >
        <div class="flex items-baseline gap-2.5 border-b border-line px-5 py-3">
          <span class="dot" :class="s.dot" />
          <h2 class="text-[13px] font-semibold">{{ s.label }}</h2>
          <span class="text-[11.5px] text-ink-faint">{{ s.hint }}</span>
          <span class="ml-auto num font-mono text-[11.5px] text-ink-faint">{{ s.items.length }}</span>
        </div>

        <p v-if="!s.items.length" class="px-5 py-4 text-[12px] text-ink-faint">{{ s.empty }}</p>

        <ul v-else class="divide-y divide-line/60">
          <li v-for="card in s.items" :key="card.id">
            <NuxtLink
              :to="'/issues/' + encodeURIComponent(card.id)"
              class="group flex items-center gap-3 px-5 py-3.5 transition-colors hover:bg-well/40"
            >
              <div class="min-w-0 flex-1">
                <div class="flex items-baseline gap-2">
                  <span class="truncate text-[13.5px] font-medium">{{ card.title }}</span>
                  <span class="shrink-0 font-mono text-[11px] text-ink-faint">
                    {{ card.repo }}#{{ card.number }}
                  </span>
                </div>

                <div class="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[11.5px] text-ink-faint">
                  <template v-if="card.state === 'waiting'">
                    <span class="text-ink-soft">{{ card.state_reason }}</span>
                    <span v-if="card.waiting_since">·</span>
                    <span v-if="card.waiting_since">{{ since(card.waiting_since) }}开始等</span>
                  </template>
                  <template v-else-if="card.state === 'running'">
                    <span>第 {{ card.rounds }} 轮</span>
                    <span>·</span>
                    <span class="text-ink-soft">{{ card.state_reason }}</span>
                  </template>
                  <template v-else>
                    <span class="text-ink-soft">{{ card.conclusion }}</span>
                    <span>·</span>
                    <span>{{ since(card.updated_at) }}</span>
                  </template>
                </div>
              </div>

              <!-- 右边只放一件与"要不要你"有关的事 -->
              <span v-if="card.state === 'waiting'" class="chip shrink-0 chip-warn">
                {{ actionLabel(card.action) || '等你' }}
              </span>
              <span
                v-else-if="card.state === 'landed'"
                class="chip shrink-0"
                :class="outcomeChip(card.verdict, card.undoable).cls"
              >
                {{ outcomeChip(card.verdict, card.undoable).label }}
              </span>
              <span v-else class="chip shrink-0 chip-info">在跑</span>

              <span v-if="card.branch" class="hidden shrink-0 font-mono text-[11px] text-ink-faint lg:inline">
                {{ card.branch }}
              </span>

              <AppIcon
                name="chevron-right"
                :size="14"
                class="shrink-0 text-ink-faint opacity-0 transition-opacity group-hover:opacity-100"
              />
            </NuxtLink>
          </li>
        </ul>
      </section>
    </template>

    <!-- 插件往这里放卡片;没有插件时不留占位,首页不该为不存在的东西留一块地 -->
    <PluginSlot
      slot="issue-board.bento"
      hide-empty
      empty-hint="插件可以在这里补充议题列表之外的卡片。"
    />
  </div>
</template>
