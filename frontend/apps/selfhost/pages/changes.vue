<script setup lang="ts">
import { ChangesApi } from '@gwei/core/api/client'
import { useChanges } from '@gwei/core/composables/useChanges'
import type { ChangeRow, ChangeVerdict } from '@gwei/core/types/changes'

const { items, total, loading, error, rollingBack, refresh, rollback } = useChanges()

const filter = ref<'all' | ChangeVerdict>('all')
const selected = ref<ChangeRow | null>(null)
const detail = ref<{ latest: ChangeRow; history: ChangeRow[] } | null>(null)
const detailLoading = ref(false)
const confirming = ref(false)

const verdictMeta: Record<ChangeVerdict, { label: string; cls: string }> = {
  kept: { label: '已执行 · 可撤', cls: 'chip-lime' },
  blocked: { label: '阻断等人', cls: 'chip-warn' },
  rolled_back: { label: '已回滚', cls: '' },
  irreversible: { label: '不可逆', cls: 'chip-bad' },
  vetoed: { label: '被否决', cls: '' },
  pending: { label: '进行中', cls: 'chip-info' },
}

const order: ChangeVerdict[] = ['kept', 'blocked', 'rolled_back', 'irreversible', 'vetoed', 'pending']

const counts = computed(() => {
  const c: Record<string, number> = {}
  for (const row of items.value) c[row.verdict] = (c[row.verdict] ?? 0) + 1
  return c
})

const visible = computed(() =>
  filter.value === 'all' ? items.value : items.value.filter(r => r.verdict === filter.value),
)

const current = computed<ChangeRow | null>(() => detail.value?.latest ?? selected.value)

function when(iso: string) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso.slice(0, 19).replace('T', ' ')
  const p = (n: number) => String(n).padStart(2, '0')
  return p(d.getMonth() + 1) + '-' + p(d.getDate()) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes())
}

function canRollback(row: ChangeRow | null) {
  return Boolean(row && row.handle && row.verdict === 'kept')
}

async function open(row: ChangeRow) {
  selected.value = row
  detail.value = null
  detailLoading.value = true
  confirming.value = false
  try {
    detail.value = await ChangesApi.get(row.id)
  } catch {
    detail.value = { latest: row, history: [] }
  } finally {
    detailLoading.value = false
  }
}

function close() {
  selected.value = null
  detail.value = null
  confirming.value = false
}

async function onRollback() {
  if (!selected.value) return
  if (!confirming.value) {
    confirming.value = true
    return
  }
  await rollback(selected.value.id)
  confirming.value = false
  close()
}

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape') close()
}

onMounted(() => window.addEventListener('keydown', onKey))
onUnmounted(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <div class="space-y-4">
    <PageHeader
      eyebrow="LEDGER"
      title="变更账本"
      description="每一次改变都是一条可回滚的事件，不是一个被覆盖的字段。"
    >
      <template #actions>
        <span class="eyebrow">{{ total }} 条记录</span>
        <button class="btn-outline btn-sm" :disabled="loading" @click="refresh()">
          <AppIcon name="refresh" :size="13" :class="loading ? 'animate-spin' : ''" />
          刷新
        </button>
      </template>
    </PageHeader>

    <div class="no-scrollbar flex items-center gap-1 overflow-x-auto pb-1">
      <button class="tab" :class="filter === 'all' ? 'tab-active' : ''" @click="filter = 'all'">
        全部
        <span class="num font-mono text-[10px] opacity-60">{{ items.length }}</span>
      </button>
      <button
        v-for="v in order"
        :key="v"
        class="tab"
        :class="filter === v ? 'tab-active' : ''"
        @click="filter = v"
      >
        {{ verdictMeta[v].label }}
        <span class="num font-mono text-[10px] opacity-60">{{ counts[v] ?? 0 }}</span>
      </button>
    </div>

    <div v-if="error" class="panel border-coral/30 bg-coral/5 p-4 text-[12.5px] text-coral">
      {{ error }}
    </div>

    <div class="panel overflow-hidden">
      <div v-if="loading && !items.length" class="space-y-px">
        <div v-for="i in 5" :key="i" class="h-[62px] animate-pulse bg-well/60" />
      </div>

      <div v-else-if="!visible.length">
        <EmptyState
          icon="scroll-text"
          title="账本还是空的"
          hint="引擎把第一条变更记进来之后,这里就是它的一生。"
        />
      </div>

      <div v-else class="overflow-x-auto">
        <table class="w-full min-w-[720px] border-collapse text-left">
          <thead>
            <tr class="border-b border-line bg-well/40">
              <th class="px-4 py-2.5 font-normal"><span class="mono-label">结论</span></th>
              <th class="px-4 py-2.5 font-normal"><span class="mono-label">意图</span></th>
              <th class="px-4 py-2.5 font-normal"><span class="mono-label">能力</span></th>
              <th class="px-4 py-2.5 font-normal"><span class="mono-label">绑定</span></th>
              <th class="px-4 py-2.5 font-normal"><span class="mono-label">时间</span></th>
              <th class="px-4 py-2.5 text-right font-normal"><span class="mono-label">操作</span></th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in visible"
              :key="row.id"
              class="group cursor-pointer border-b border-line/60 transition-colors last:border-0 hover:bg-well/40"
              @click="open(row)"
            >
              <td class="px-4 py-3">
                <span class="chip whitespace-nowrap" :class="verdictMeta[row.verdict].cls">
                  {{ verdictMeta[row.verdict].label }}
                </span>
              </td>
              <td class="max-w-[280px] px-4 py-3">
                <div class="truncate text-[13px] font-medium">
                  {{ row.intent?.summary || '(无摘要)' }}
                </div>
                <div class="mt-0.5 truncate font-mono text-[10.5px] text-ink-faint">{{ row.id }}</div>
              </td>
              <td class="px-4 py-3">
                <span class="font-mono text-[11.5px] text-ink-soft">{{ row.effect?.capability || '—' }}</span>
              </td>
              <td class="px-4 py-3">
                <span class="font-mono text-[11.5px] text-ink-soft">{{ row.binding || '—' }}</span>
              </td>
              <td class="px-4 py-3">
                <span class="num font-mono text-[11.5px] text-ink-faint">{{ when(row.created_at) }}</span>
              </td>
              <td class="px-4 py-3 text-right">
                <span
                  v-if="canRollback(row)"
                  class="rounded-full border border-line px-2.5 py-1 text-[11px] font-medium text-ink-soft transition-colors group-hover:border-coral/40 group-hover:text-coral"
                >
                  撤销
                </span>
                <AppIcon
                  v-else
                  name="chevron-right"
                  :size="14"
                  class="ml-auto text-ink-faint opacity-0 transition-opacity group-hover:opacity-100"
                />
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 详情抽屉:磨砂玻璃 -->
    <Teleport to="body">
      <div v-if="selected" class="fixed inset-0 z-50">
        <div class="absolute inset-0 animate-fade bg-ink/25 backdrop-blur-sm" @click="close" />

        <aside
          class="glass absolute right-0 top-0 flex h-full w-full max-w-[540px] animate-slide flex-col border-l border-line/70"
          role="dialog"
          aria-modal="true"
        >
          <div class="flex items-start justify-between gap-3 border-b border-line/60 px-5 py-4">
            <div class="min-w-0">
              <span class="chip" :class="current ? verdictMeta[current.verdict].cls : ''">
                {{ current ? verdictMeta[current.verdict].label : '' }}
              </span>
              <h2 class="mt-2.5 line-clamp-2 text-[15px] font-semibold leading-snug">
                {{ current?.intent?.summary || '(无摘要)' }}
              </h2>
            </div>
            <button class="btn-icon shrink-0" aria-label="关闭" @click="close">
              <AppIcon name="x" :size="15" />
            </button>
          </div>

          <div class="flex-1 space-y-5 overflow-auto px-5 py-5">
            <div v-if="detailLoading" class="space-y-2">
              <div v-for="i in 6" :key="i" class="h-9 animate-pulse rounded-lg bg-well/70" />
            </div>

            <template v-else-if="current">
              <dl class="overflow-hidden rounded-xl border border-line/70">
                <div
                  v-for="row in [
                    { k: '能力', v: current.effect?.capability || '—' },
                    { k: '提供者任务', v: current.effect?.task || '—' },
                    { k: '绑定', v: current.binding || '—' },
                    { k: '租户', v: current.tenant || '—' },
                    { k: '句柄', v: current.handle || '—' },
                    { k: '幂等键', v: current.idempotency_key || '—' },
                    { k: '单元 id', v: current.id },
                    { k: '记录时间', v: current.created_at },
                  ]"
                  :key="row.k"
                  class="flex items-start gap-3 border-b border-line/60 px-4 py-2.5 last:border-0"
                >
                  <dt class="w-24 shrink-0 pt-0.5 text-[11.5px] text-ink-faint">{{ row.k }}</dt>
                  <dd class="min-w-0 flex-1 break-all font-mono text-[12px] leading-relaxed text-ink-soft">
                    {{ row.v }}
                  </dd>
                </div>
              </dl>

              <div v-if="current.reason" class="rounded-xl border border-line/70 bg-well/50 p-4">
                <div class="mono-label">原因</div>
                <p class="mt-1.5 text-[12.5px] leading-relaxed text-ink-soft">{{ current.reason }}</p>
              </div>

              <div v-if="detail?.history?.length">
                <div class="mono-label mb-2.5">这条变更的历史</div>
                <ol class="relative space-y-3 pl-4">
                  <span class="absolute left-[3px] top-1.5 h-[calc(100%-12px)] w-px bg-line" />
                  <li v-for="(h, i) in detail.history" :key="i" class="relative">
                    <span class="absolute -left-4 top-1.5 h-1.5 w-1.5 rounded-full bg-ink-faint" />
                    <div class="flex flex-wrap items-center gap-2">
                      <span class="text-[12px] font-medium">{{ verdictMeta[h.verdict].label }}</span>
                      <span class="num font-mono text-[10.5px] text-ink-faint">{{ when(h.created_at) }}</span>
                    </div>
                    <p v-if="h.reason" class="mt-0.5 text-[11.5px] text-ink-soft">{{ h.reason }}</p>
                  </li>
                </ol>
              </div>
            </template>
          </div>

          <div class="border-t border-line/60 px-5 py-4">
            <template v-if="canRollback(current)">
              <button
                class="btn w-full"
                :class="confirming
                  ? 'bg-coral text-white hover:bg-coral/90'
                  : 'border border-line bg-panel text-ink hover:border-coral/40 hover:text-coral'"
                :disabled="rollingBack === selected?.id"
                @click="onRollback"
              >
                <AppIcon :name="confirming ? 'x-circle' : 'rotate-ccw'" :size="14" />
                {{ rollingBack === selected?.id ? '正在回滚…' : confirming ? '再点一次确认撤销' : '撤销这次变更' }}
              </button>
              <p class="mt-2 text-center text-[11px] text-ink-faint">
                撤销本身也会作为一条事件记进账本。
              </p>
            </template>
            <p v-else class="text-center text-[11.5px] text-ink-faint">
              这条变更当前没有可撤销的句柄。
            </p>
          </div>
        </aside>
      </div>
    </Teleport>
  </div>
</template>
