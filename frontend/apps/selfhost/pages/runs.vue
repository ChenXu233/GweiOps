<script setup lang="ts">
import { useRuns } from '@gwei/core/composables/useRuns'
import type { RunRow } from '@gwei/core/types/runs'
import type { Tone } from '@gwei/core/utils/tone'

const { items, total, loading, error, refresh } = useRuns()

type RunFilter = 'all' | 'running' | 'ended'

const filter = ref<RunFilter>('all')
const expandedId = ref<string | null>(null)

const endedRows = computed(() => items.value.filter((r) => r.endedAt !== null))
const runningCount = computed(() => items.value.filter((r) => r.endedAt === null).length)
const failedCount = computed(() => endedRows.value.filter((r) => /FAILED|ERROR/i.test(r.status)).length)
/** 分母是「已结束的执行」;没有已结束的会话时是 null,不是 0 也不是 100%。 */
const successRate = computed<number | null>(() => {
  const ended = endedRows.value.length
  if (ended === 0) return null
  return ((ended - failedCount.value) / ended) * 100
})

const visible = computed(() => {
  if (filter.value === 'running') return items.value.filter((r) => r.endedAt === null)
  if (filter.value === 'ended') return endedRows.value
  return items.value
})

const sourceLabels: Record<string, string> = {
  issue: '议题触发',
  comment: '评论触发',
}

/** 状态原样显示,颜色只用来区分「跑着 / 成 / 败 / 不认识」。 */
function toneFor(row: RunRow): Tone {
  if (row.endedAt === null) return 'info'
  if (/FAILED|ERROR/i.test(row.status)) return 'bad'
  if (/COMPLETED|SUCCESS|DONE|APPROVED/i.test(row.status)) return 'ok'
  return 'idle'
}

function sourceLabel(source: string): string {
  return sourceLabels[source] ?? source
}

function when(value: string | null | undefined): string {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value.slice(0, 19).replace('T', ' ')
  const p = (n: number) => String(n).padStart(2, '0')
  return (
    p(d.getMonth() + 1) +
    '-' +
    p(d.getDate()) +
    ' ' +
    p(d.getHours()) +
    ':' +
    p(d.getMinutes()) +
    ':' +
    p(d.getSeconds())
  )
}

/** 没结束就没有耗时,这里留空,不拿 0 凑。 */
function duration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return '—'
  if (ms >= 1000) return (ms / 1000).toFixed(1) + ' s'
  return ms + ' ms'
}

function stateValue(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  try {
    return JSON.stringify(value, null, 2) ?? String(value)
  } catch {
    return String(value)
  }
}

function stateEntries(row: RunRow): Array<[string, unknown]> {
  return Object.entries(row.state ?? {})
}

function toggle(row: RunRow) {
  expandedId.value = expandedId.value === row.id ? null : row.id
}
</script>

<template>
  <div class="space-y-4">
    <PageHeader
      eyebrow="RUNS"
      title="执行记录"
      description="每一次 AgentSession 就是一次执行。谁在什么时候、为哪个议题做了什么,这里摊开成可查的记录。"
    >
      <template #actions>
        <button class="btn-outline btn-sm" :disabled="loading" @click="refresh">
          <AppIcon name="refresh" :size="13" :class="loading ? 'animate-spin' : ''" />
          刷新
        </button>
      </template>
    </PageHeader>

    <!-- 取数失败:引擎没起来或接口报错,先把话说清楚 -->
    <div v-if="error" class="panel border-coral/30 bg-coral/5 p-4 text-[12.5px] text-coral">
      <div class="flex items-start gap-2">
        <AppIcon name="alert" :size="14" class="mt-0.5" />
        <div class="min-w-0">
          <p class="font-medium">拉不到执行记录。</p>
          <p class="mt-1 break-words text-[11.5px] text-coral/80">{{ error }}</p>
        </div>
      </div>
    </div>

    <!-- 概览 -->
    <div class="grid gap-3 sm:grid-cols-3">
      <div class="tile">
        <div class="eyebrow">执行总数</div>
        <div class="num mt-2 text-[22px] font-semibold leading-none sm:text-[26px]">{{ total }}</div>
        <div class="mt-2 text-[11.5px] leading-relaxed text-ink-faint">引擎记录过的会话数</div>
      </div>

      <div class="tile">
        <div class="eyebrow">进行中</div>
        <div class="num mt-2 text-[22px] font-semibold leading-none sm:text-[26px]">{{ runningCount }}</div>
        <div class="mt-2 text-[11.5px] leading-relaxed text-ink-faint">还没结束的执行</div>
      </div>

      <div class="tile">
        <div class="eyebrow">成功率</div>
        <div class="mt-2 leading-none">
          <span v-if="successRate === null" class="text-[13px] leading-snug text-ink-faint">
            暂无已结束的执行
          </span>
          <span v-else class="num text-[22px] font-semibold sm:text-[26px]">{{ successRate.toFixed(1) }}%</span>
        </div>
        <div class="mt-2 text-[11.5px] leading-relaxed text-ink-faint">
          <template v-if="successRate === null">结束一次执行后才有分母</template>
          <template v-else>{{ endedRows.length }} 次已结束执行中,{{ failedCount }} 次失败</template>
        </div>
      </div>
    </div>

    <p class="text-[11.5px] text-ink-faint">
      进行中与成功率按本次加载的 {{ items.length }} 条记录统计;引擎共记录 {{ total }} 次执行。
    </p>

    <!-- 过滤 -->
    <div class="no-scrollbar flex items-center gap-1 overflow-x-auto pb-1">
      <button class="tab" :class="filter === 'all' ? 'tab-active' : ''" @click="filter = 'all'">
        全部
        <span class="num font-mono text-[10px] opacity-60">{{ items.length }}</span>
      </button>
      <button
        class="tab"
        :class="filter === 'running' ? 'tab-active' : ''"
        @click="filter = 'running'"
      >
        进行中
        <span class="num font-mono text-[10px] opacity-60">{{ runningCount }}</span>
      </button>
      <button
        class="tab"
        :class="filter === 'ended' ? 'tab-active' : ''"
        @click="filter = 'ended'"
      >
        已结束
        <span class="num font-mono text-[10px] opacity-60">{{ endedRows.length }}</span>
      </button>
    </div>

    <!-- 明细 -->
    <div class="panel overflow-hidden">
      <div v-if="loading && !items.length" class="space-y-2 p-4">
        <div v-for="i in 6" :key="i" class="h-9 skeleton" />
      </div>

      <EmptyState
        v-else-if="!items.length && !error"
        icon="runs"
        title="还没有执行记录"
        hint="引擎接住一个 GitHub 事件、开会话跑一轮诊断,这里就多一行——夜里到底跑了什么,翻得出来。"
      />

      <p v-else-if="!items.length" class="px-5 py-10 text-center text-[12px] text-ink-faint">
        接口这次没给出记录,原因见上面的提示。
      </p>

      <div v-else class="overflow-x-auto">
        <table class="w-full min-w-[880px] border-collapse text-left">
          <thead>
            <tr class="border-b border-line bg-well/40">
              <th class="w-9 px-3 py-2.5 font-normal"></th>
              <th class="px-4 py-2.5 font-normal"><span class="mono-label">状态</span></th>
              <th class="px-4 py-2.5 font-normal"><span class="mono-label">时间</span></th>
              <th class="px-4 py-2.5 font-normal"><span class="mono-label">议题</span></th>
              <th class="px-4 py-2.5 font-normal"><span class="mono-label">仓库</span></th>
              <th class="px-4 py-2.5 font-normal"><span class="mono-label">来源</span></th>
              <th class="px-4 py-2.5 text-right font-normal"><span class="mono-label">耗时</span></th>
            </tr>
          </thead>
          <tbody>
            <template v-for="row in visible" :key="row.id">
              <tr
                class="group cursor-pointer border-b border-line/60 transition-colors hover:bg-well/40 focus:bg-well/40 focus:outline-none"
                tabindex="0"
                @click="toggle(row)"
                @keydown.enter.prevent="toggle(row)"
                @keydown.space.prevent="toggle(row)"
              >
                <td class="px-3 py-3">
                  <AppIcon
                    name="chevron-right"
                    :size="13"
                    class="text-ink-faint transition-transform duration-220 ease-[var(--ease)]"
                    :class="expandedId === row.id ? 'rotate-90' : ''"
                  />
                </td>

                <td class="whitespace-nowrap px-4 py-3">
                  <StatusPip :tone="toneFor(row)" :pulse="row.endedAt === null">
                    <span class="font-mono">{{ row.status }}</span>
                  </StatusPip>
                </td>

                <td class="whitespace-nowrap px-4 py-3">
                  <span class="num font-mono text-[11.5px] text-ink-faint">{{ when(row.startedAt) }}</span>
                </td>

                <td class="max-w-[320px] px-4 py-3">
                  <NuxtLink
                    :to="`/issues/${row.issueId}`"
                    class="block"
                    title="打开这个议题"
                    @click.stop
                  >
                    <div class="truncate text-[13px] font-medium hover:underline">
                      {{ row.issueTitle }}
                    </div>
                    <div class="mt-0.5 font-mono text-[10.5px] text-ink-faint">
                      #{{ row.issueNumber }}
                    </div>
                  </NuxtLink>
                </td>

                <td class="max-w-[200px] px-4 py-3">
                  <span class="block truncate font-mono text-[11.5px] text-ink-soft">{{ row.repo }}</span>
                </td>

                <td class="whitespace-nowrap px-4 py-3">
                  <span class="chip">{{ sourceLabel(row.source) }}</span>
                </td>

                <td class="whitespace-nowrap px-4 py-3 text-right">
                  <span
                    class="num font-mono text-[11.5px]"
                    :class="row.durationMs === null ? 'text-ink-faint' : 'text-ink-soft'"
                  >
                    {{ duration(row.durationMs) }}
                  </span>
                </td>
              </tr>

              <tr v-if="expandedId === row.id" class="border-b border-line/60 bg-well/40">
                <td colspan="7" class="px-4 py-4">
                  <div class="rounded-card border border-line-soft bg-panel p-4">
                    <div class="flex flex-wrap items-center justify-between gap-2">
                      <span class="mono-label">这次执行的附加状态</span>
                      <span class="font-mono text-[10.5px] text-ink-faint">{{ row.id }}</span>
                    </div>

                    <p
                      v-if="!stateEntries(row).length"
                      class="mt-3 text-[12px] text-ink-faint"
                    >
                      没有附加状态
                    </p>

                    <dl v-else class="mt-3 space-y-2">
                      <div
                        v-for="[key, value] in stateEntries(row)"
                        :key="key"
                        class="grid grid-cols-[minmax(0,132px)_minmax(0,1fr)] gap-x-3 gap-y-1 sm:grid-cols-[minmax(0,160px)_minmax(0,1fr)]"
                      >
                        <dt class="font-mono text-[10.5px] uppercase tracking-[0.12em] text-ink-faint">
                          {{ key }}
                        </dt>
                        <dd class="whitespace-pre-wrap break-all font-mono text-[11.5px] leading-relaxed text-ink-soft">
                          {{ stateValue(value) }}
                        </dd>
                      </div>
                    </dl>

                    <div
                      class="mt-4 flex flex-wrap gap-x-6 gap-y-1 border-t border-line/70 pt-3 font-mono text-[10.5px] text-ink-faint"
                    >
                      <span>开始 {{ row.startedAt ?? '—' }}</span>
                      <span>结束 {{ row.endedAt ?? '—' }}</span>
                      <span>来源 {{ row.source }}</span>
                    </div>
                  </div>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
    </div>

    <p v-if="items.length" class="text-[11.5px] text-ink-faint">
      显示最近 {{ items.length }} 条,引擎共记录 {{ total }} 次执行。
    </p>
  </div>
</template>