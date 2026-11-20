<script setup lang="ts">
// 议题详情:头部结论 + 时间线 + 动作。
//
// 页面只做三件事:把后端给的一句话结论放在最上面、把一条线按轮次摊开、在
// **那一段该你动手的地方**给出按钮。没有动作就什么都不留——灰按钮是噪声。
// 证据默认收起:概要层一句人话,点开才是原文,截断了要明说。
import { useIssueTimeline } from '@gwei/core/composables/useIssueTimeline'
import type { SegmentKind, TimelineEvidence, TimelineSegment } from '@gwei/core/types/issues'
import { outcomeChip, stateMeta, verdictLabel } from '@gwei/core/utils/verdict'
import { useWorkspaces } from '@gwei/core/composables/useWorkspaces'
import { useRouteParam } from '~/composables/useRouteParam'

// 页面里的每个链接都带上工作区那一段:链接点了、刷新、转发出去都还是同一道账。
const { hrefFor: scopedTo } = useWorkspaces()
const id = useRouteParam('id')
const { data, loading, error, busy, refresh, act, continueRound } = useIssueTimeline(id.value)

const { can } = useAuth()
const canApprove = computed(() => can('changes.approve'))
const canRollback = computed(() => can('changes.rollback'))

type Detail = Record<string, any>

const kindMeta: Record<SegmentKind, { label: string; icon: string }> = {
  signal: { label: '信号', icon: 'siren' },
  diagnosis: { label: '诊断', icon: 'brain' },
  intent: { label: '意图', icon: 'sparkles' },
  change: { label: '变更', icon: 'zap' },
  verify: { label: '验证', icon: 'shield-check' },
  conclusion: { label: '结论', icon: 'check-circle' },
}

const undoKindLabel: Record<string, string> = {
  symmetric: '对称操作撤回去',
  retained: '靠下游留着的旧状态撤回去',
}

function detailOf(seg: TimelineSegment): Detail {
  return (seg.detail ?? {}) as Detail
}

function verdictOf(seg: TimelineSegment) {
  return String(detailOf(seg).verdict ?? '')
}

function unitOf(seg: TimelineSegment) {
  return String(detailOf(seg).unit_id ?? '')
}

function when(iso: string) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso.slice(0, 16).replace('T', ' ')
  const p = (n: number) => String(n).padStart(2, '0')
  return p(d.getMonth() + 1) + '-' + p(d.getDate()) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes())
}

function outcomeOf(seg: TimelineSegment) {
  const d = detailOf(seg)
  return outcomeChip(
    String(d.verdict ?? ''),
    d.undoable === true,
    String(d.undo_expires_at ?? ''),
  )
}

/** 决策要点四块:打算做什么、为什么、影响面、怎么撤。常驻,不折叠。 */
function detailRows(seg: TimelineSegment) {
  const d = detailOf(seg)
  const rows: Array<{ k: string; v: string; block?: boolean }> = []
  const push = (k: string, v: unknown, block = false) => {
    if (v === undefined || v === null || v === '') return
    if (Array.isArray(v) && !v.length) return
    if (typeof v === 'string') {
      rows.push({ k, v })
      return
    }
    if (typeof v === 'number' || typeof v === 'boolean') {
      rows.push({ k, v: String(v) })
      return
    }
    rows.push({ k, v: JSON.stringify(v, null, 2), block: block || true })
  }
  const capabilities = (list: unknown) =>
    Array.isArray(list) ? list.map((c) => (c && c.capability ? c.capability : '')).filter(Boolean) : []
  // 没执行的候选:有理由就连理由一起说,只有名单就说只有名单
  const skippedText = (list: unknown) =>
    Array.isArray(list)
      ? list
          .map((c) => (c?.capability ? (c.reason ? c.capability + ' — ' + c.reason : c.capability) : ''))
          .filter(Boolean)
          .join('；')
      : ''
  // 查了什么:声明里的 {query, expect}
  const rulesText = (list: unknown) =>
    Array.isArray(list)
      ? list
          .map((r) => (r?.query ? r.query + '(期望 ' + (r.expect ?? '—') + ')' : ''))
          .filter(Boolean)
          .join(' · ')
      : ''

  switch (seg.kind) {
    case 'signal':
      push('来源', d.source)
      break
    case 'diagnosis':
      push('标签', Array.isArray(d.labels) ? d.labels.join(' · ') : d.labels)
      push('完整度', d.completeness_score)
      break
    case 'intent':
      push('为什么这样做', d.rationale)
      push('候选动作', capabilities(d.candidates).join(' · '))
      push('没有执行', skippedText(d.not_executed))
      push('谁让它改的', d.by)
      push('工具', d.tool)
      break
    case 'change':
      push('动作', d.capability)
      push('提供者任务', d.task)
      push('作用在', d.binding)
      push('参数', d.args, true)
      push(
        '怎么撤',
        d.undo_task ? d.undo_task + '(' + (undoKindLabel[String(d.undo_kind)] ?? d.undo_kind) + ')' : '',
      )
      break
    case 'verify':
      push('查了什么', rulesText(d.rules))
      push('下游返回', d.returned, true)
      push('报错', d.error, true)
      break
    case 'conclusion':
      push('还能撤吗', d.undo_reason)
      push('窗口', d.window, true)
      push('句柄', d.handle)
      break
  }
  return rows
}

function evidenceText(ev: TimelineEvidence) {
  const content = (ev as { content?: unknown }).content
  if (typeof content === 'string') return content
  return JSON.stringify(content, null, 2)
}

const open = ref<Record<string, boolean>>({})
function toggle(key: string) {
  open.value = { ...open.value, [key]: !open.value[key] }
}

const confirming = ref<string | null>(null)
function canUndo(seg: TimelineSegment) {
  return (
    canRollback.value &&
    verdictOf(seg) === 'kept' &&
    detailOf(seg).undoable === true &&
    Boolean(unitOf(seg))
  )
}

async function run(seg: TimelineSegment, action: 'approve' | 'veto' | 'rollback') {
  const unit = unitOf(seg)
  if (!unit) return
  // 撤销不可逆,点两次:第一次只把按钮换成"再点一次确认"。
  if (action === 'rollback' && confirming.value !== unit) {
    confirming.value = unit
    return
  }
  confirming.value = null
  await act(unit, action)
}

const conclusions = computed(() =>
  (data.value?.rounds ?? []).flatMap((round) =>
    round.segments
      .filter((seg) => seg.kind === 'conclusion')
      .map((seg) => ({ seg, round: round.round })),
  ),
)

/** 此刻有没有需要人动手的地方:有就说明在哪儿,没有就明说没有。 */
// 每一轮改了哪些文件。行数是平台从工作区数的,不是 agent 自报的。
const diffStatus: Record<string, { label: string; cls: string }> = {
  added: { label: '新增', cls: 'text-ok' },
  modified: { label: '修改', cls: 'text-ink-soft' },
  deleted: { label: '删除', cls: 'text-coral' },
}

function totals(rows: { added: number; removed: number }[]) {
  return rows.reduce(
    (sum, row) => ({ added: sum.added + row.added, removed: sum.removed + row.removed }),
    { added: 0, removed: 0 },
  )
}

/** 跨轮合并:同一分支上多轮改同一个文件时,按路径累加。 */
const merged = computed(() => {
  const sums = new Map<string, { path: string; added: number; removed: number }>()
  for (const round of data.value?.rounds ?? []) {
    for (const file of round.diff ?? []) {
      const cur = sums.get(file.path) ?? { path: file.path, added: 0, removed: 0 }
      cur.added += file.added
      cur.removed += file.removed
      sums.set(file.path, cur)
    }
  }
  const files = [...sums.values()].sort((a, b) => a.path.localeCompare(b.path))
  return { files, ...totals(files) }
})

// 继续改:一轮一轮往下写。没有分支时照样能写——第一轮会开分支,后面复用它。
const draft = ref('')
const queued = ref(false)

async function submitRound() {
  const text = draft.value.trim()
  if (!text || busy.value === 'continue') return
  queued.value = false
  try {
    await continueRound(text)
    draft.value = ''
    queued.value = true
  } catch {
    // 错误已经进了 composable 的 error,这里只保留输入框里的字
  }
}

const needsHuman = computed(() =>
  conclusions.value.some(
    (c) =>
      (verdictOf(c.seg) === 'blocked' && canApprove.value) ||
      verdictOf(c.seg) === 'unknown' ||
      canUndo(c.seg),
  ),
)
</script>

<template>
  <div class="space-y-5">
    <NuxtLink
      :to="scopedTo('/issues')"
      class="inline-flex items-center gap-1.5 text-[12px] font-medium text-ink-faint transition-colors hover:text-ink"
    >
      <AppIcon name="arrow-right" :size="13" class="rotate-180" />
      回到议题
    </NuxtLink>

    <div v-if="loading" class="space-y-3">
      <div class="h-8 w-2/3 animate-pulse rounded-lg bg-well" />
      <div class="h-4 w-1/3 animate-pulse rounded bg-well" />
    </div>

    <div v-else-if="error && !data" class="panel p-6">
      <p class="text-[13px] font-medium">读不到这个议题</p>
      <p class="mt-1 text-[12px] text-ink-soft">{{ error }}</p>
      <button class="btn-outline btn-sm mt-3" @click="refresh()">重试</button>
    </div>

    <div v-else-if="!data" class="panel p-6">
      <p class="text-[13px] font-medium">找不到这个议题</p>
      <p class="mt-1 text-[12px] text-ink-soft">它可能已经完成并被归档。</p>
    </div>

    <template v-else>
      <!-- 头部:一句话结论 -->
      <header class="panel p-5 sm:p-6">
        <div class="flex flex-wrap items-center gap-2">
          <span class="chip" :class="stateMeta[data.state].cls">{{ stateMeta[data.state].label }}</span>
          <span class="font-mono text-[11.5px] text-ink-faint">{{ data.topic || data.repo }}</span>
          <span v-if="data.truncated" class="chip chip-warn">只看了一部分</span>
        </div>

        <h1 class="mt-3 max-w-3xl text-[24px] font-semibold leading-tight tracking-tightest">
          {{ data.title }}
        </h1>

        <p class="mt-2.5 text-[13.5px] leading-relaxed text-ink-soft">{{ data.state_reason }}</p>

        <!-- 需要人动手时,上面那句已经说清了在等什么;不需要时才要明说一句"没事"。 -->
        <div v-if="!needsHuman" class="mt-3 flex items-center gap-2 text-[12px] text-ink-faint">
          <AppIcon name="check" :size="12" />
          <span>现在不需要你做什么。</span>
        </div>

        <div class="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 font-mono text-[11.5px] text-ink-faint">
          <span class="flex items-center gap-1.5">
            <AppIcon name="repos" :size="12" />{{ data.repo }}
          </span>
          <span class="flex items-center gap-1.5">
            <AppIcon name="hash" :size="12" />#{{ data.number }}
          </span>
          <template v-if="data.branch">
            <span class="flex items-center gap-1.5">
              <AppIcon name="layers" :size="12" />{{ data.branch.head }}
            </span>
            <a
              v-if="data.branch.url"
              :href="data.branch.url"
              target="_blank"
              rel="noreferrer"
              class="flex items-center gap-1.5 text-ink-soft transition-colors hover:text-ink"
            >
              <AppIcon name="external-link" :size="12" />PR #{{ data.branch.pull }}
            </a>
            <span v-else class="flex items-center gap-1.5">PR #{{ data.branch.pull }}</span>
          </template>
        </div>
      </header>

      <div v-if="error" class="panel border-coral/30 bg-coral/5 p-4 text-[12.5px] text-coral">
        {{ error }}
      </div>

      <div class="grid grid-cols-12 items-start gap-4">
        <!-- 时间线 -->
        <section class="panel col-span-12 overflow-hidden lg:col-span-8">
          <div class="flex items-center justify-between border-b border-line px-5 py-3.5">
            <h2 class="text-[13px] font-semibold">时间线</h2>
            <span class="ml-auto mr-3 font-mono text-[11px] text-ink-faint">
              <template v-if="merged.files.length">
                合计 {{ merged.files.length }} 个文件
                <span class="text-ok">+{{ merged.added }}</span>
                <span class="text-coral">−{{ merged.removed }}</span>
              </template>
            </span>
            <span class="mono-label">TIMELINE</span>
          </div>

          <EmptyState
            v-if="!data.rounds.length"
            icon="inbox"
            title="还没有开始"
            hint="这个议题收到之后,引擎还没动过手——信号、诊断、意图会依次出现在这里。"
          />

          <div v-else class="px-5 py-5">
            <div v-for="round in data.rounds" :key="round.key" class="pb-6 last:pb-0">
              <div class="mb-2 flex flex-wrap items-baseline gap-2">
                <span class="text-[12.5px] font-semibold">第 {{ round.round }} 轮</span>
                <span class="num font-mono text-[11px] text-ink-faint">{{ when(round.at) }}</span>
                <span v-if="round.summary" class="text-[12px] leading-relaxed text-ink-soft">
                  {{ round.summary }}
                </span>
                <span class="ml-auto flex flex-wrap gap-1">
                  <span v-for="(_, v) in round.verdicts" :key="v" class="chip">
                    {{ verdictLabel(String(v)) }}
                  </span>
                </span>
              </div>

              <!-- 这一轮改了哪些文件:行数是平台数的 -->
              <div v-if="round.diff?.length" class="mb-3 flex flex-wrap items-center gap-2">
                <span class="mono-label">改动</span>
                <span class="text-[11.5px] text-ink-soft">{{ round.diff.length }} 个文件</span>
                <span class="font-mono text-[11.5px] text-ok">+{{ totals(round.diff).added }}</span>
                <span class="font-mono text-[11.5px] text-coral">−{{ totals(round.diff).removed }}</span>
                <button
                  class="text-[11.5px] font-medium text-ink-faint transition-colors hover:text-ink"
                  @click="toggle('diff:' + round.key)"
                >
                  {{ open['diff:' + round.key] ? '收起文件' : '看文件' }}
                </button>
              </div>
              <ul v-if="open['diff:' + round.key]" class="mb-3 space-y-1 rounded-tile bg-well/30 px-3 py-2">
                <li
                  v-for="file in round.diff"
                  :key="file.path"
                  class="flex items-baseline gap-2 font-mono text-[11px]"
                >
                  <span class="w-8 shrink-0" :class="diffStatus[file.status]?.cls">
                    {{ diffStatus[file.status]?.label }}
                  </span>
                  <span class="min-w-0 flex-1 truncate text-ink-soft">{{ file.path }}</span>
                  <span class="shrink-0 text-ok">+{{ file.added }}</span>
                  <span class="shrink-0 text-coral">−{{ file.removed }}</span>
                </li>
              </ul>

              <ol class="relative pl-5">
                <span class="absolute left-[6px] top-2 h-[calc(100%-16px)] w-px bg-line" />

                <li v-for="seg in round.segments" :key="seg.id" class="relative pb-4 last:pb-0">
                  <span
                    class="absolute -left-5 top-0.5 grid h-[13px] w-[13px] place-items-center rounded-full border bg-panel"
                    :class="seg.kind === 'conclusion' ? 'border-ink/40' : 'border-line'"
                  >
                    <AppIcon
                      :name="kindMeta[seg.kind].icon"
                      :size="8"
                      :stroke="2.4"
                      :class="seg.kind === 'conclusion' ? 'text-ink' : 'text-ink-faint'"
                    />
                  </span>

                  <div class="flex flex-wrap items-baseline gap-2">
                    <span class="mono-label">{{ kindMeta[seg.kind].label }}</span>
                    <span class="num font-mono text-[11px] text-ink-faint">{{ when(seg.at) }}</span>
                    <span
                      v-if="seg.kind === 'conclusion'"
                      class="chip"
                      :class="outcomeOf(seg).cls"
                    >
                      {{ outcomeOf(seg).label }}
                    </span>
                  </div>

                  <p class="mt-1 text-[13px] leading-relaxed text-ink">{{ seg.summary }}</p>

                  <!-- 决策要点:常驻,不折叠 -->
                  <dl
                    v-if="detailRows(seg).length"
                    class="mt-2 overflow-hidden rounded-tile border border-line/60 bg-well/30"
                  >
                    <div
                      v-for="row in detailRows(seg)"
                      :key="row.k"
                      class="flex items-start gap-3 border-b border-line/40 px-3 py-2 last:border-0"
                    >
                      <dt class="w-[5.5rem] shrink-0 pt-0.5 text-[11.5px] text-ink-faint">{{ row.k }}</dt>
                      <dd class="min-w-0 flex-1">
                        <pre
                          v-if="row.block"
                          class="max-h-56 overflow-auto whitespace-pre-wrap break-all font-mono text-[11px] leading-relaxed text-ink-soft"
                        >{{ row.v }}</pre>
                        <span v-else class="text-[12px] leading-relaxed text-ink-soft">{{ row.v }}</span>
                      </dd>
                    </div>
                  </dl>

                  <!-- 动作:只在这一段该你动手时出现 -->
                  <div
                    v-if="seg.kind === 'conclusion'"
                    class="mt-2 flex flex-wrap items-center gap-2"
                  >
                    <template v-if="verdictOf(seg) === 'blocked' && canApprove">
                      <button
                        class="btn-solid btn-sm"
                        :disabled="busy === unitOf(seg)"
                        @click="run(seg, 'approve')"
                      >
                        <AppIcon name="play" :size="12" />
                        放行
                      </button>
                      <button
                        class="btn-outline btn-sm"
                        :disabled="busy === unitOf(seg)"
                        @click="run(seg, 'veto')"
                      >
                        否决
                      </button>
                      <span class="text-[11.5px] text-ink-faint">
                        放行后照样读窗口、照样验证,不过就回滚。
                      </span>
                    </template>

                    <template v-else-if="canUndo(seg)">
                      <button
                        class="btn-outline btn-sm"
                        :class="confirming === unitOf(seg) ? 'border-coral/50 text-coral' : ''"
                        :disabled="busy === unitOf(seg)"
                        @click="run(seg, 'rollback')"
                      >
                        <AppIcon name="rotate-ccw" :size="12" />
                        {{ confirming === unitOf(seg) ? '再点一次确认撤销' : '撤销这次变更' }}
                      </button>
                      <span class="text-[11.5px] text-ink-faint">撤销本身也会记一行账。</span>
                    </template>

                    <template v-else-if="verdictOf(seg) === 'unknown'">
                      <NuxtLink :to="scopedTo('/changes')" class="btn-outline btn-sm">
                        <AppIcon name="scroll-text" :size="12" />
                        去账本核对
                      </NuxtLink>
                      <span class="text-[11.5px] text-ink-faint">
                        不知道动没动,没有一键的解法:先去下游看一眼。
                      </span>
                    </template>

                    <span v-if="busy === unitOf(seg)" class="text-[11.5px] text-ink-faint">
                      <AppIcon name="loader" :size="12" class="inline animate-spin" /> 正在处理…
                    </span>
                  </div>

                  <!-- 证据:默认收起,原文不加工 -->
                  <div v-if="seg.evidence.length" class="mt-2">
                    <button
                      class="text-[11.5px] font-medium text-ink-faint transition-colors hover:text-ink"
                      @click="toggle(seg.id)"
                    >
                      {{ open[seg.id] ? '收起原文' : '展开原文(' + seg.evidence.length + ')' }}
                    </button>

                    <div v-if="open[seg.id]" class="mt-2 space-y-2">
                      <div
                        v-for="(ev, i) in seg.evidence"
                        :key="i"
                        class="rounded-tile border border-line/60 bg-sunken/40 p-3"
                      >
                        <div class="flex flex-wrap items-center gap-2">
                          <span class="mono-label">{{ ev.label }}</span>
                          <span v-if="ev.truncated" class="chip chip-warn">已截断</span>
                        </div>
                        <pre
                          class="mt-1.5 max-h-72 overflow-auto whitespace-pre-wrap break-all font-mono text-[11px] leading-relaxed text-ink-soft"
                        >{{ evidenceText(ev) }}</pre>
                      </div>
                    </div>
                  </div>
                </li>
              </ol>
            </div>

            <!-- 继续改:这条线还没到头,人的下一句话从这里进去 -->
            <form
              class="mt-2 border-t border-line/60 pt-4"
              @submit.prevent="submitRound"
            >
              <div class="flex items-baseline gap-2">
                <label for="continue-round" class="mono-label">继续改</label>
                <span class="text-[11.5px] text-ink-faint">
                  接着这条线再改一轮:话题与分支不变,PR 不会新开。
                </span>
              </div>
              <textarea
                id="continue-round"
                v-model="draft"
                rows="3"
                maxlength="500"
                :disabled="busy === 'continue'"
                class="mt-2 w-full resize-y rounded-control border border-line bg-panel px-3 py-2 text-[13px] leading-relaxed text-ink outline-none transition-colors placeholder:text-ink-faint focus:border-brand/60"
                placeholder="要改什么、为什么。写清楚一点,agent 会照这个改。"
              />
              <div class="mt-2 flex flex-wrap items-center gap-2">
                <button
                  type="submit"
                  class="btn-solid btn-sm"
                  :disabled="!draft.trim() || busy === 'continue'"
                >
                  <AppIcon name="arrow-right" :size="12" />
                  开一轮
                </button>
                <span v-if="busy === 'continue'" class="text-[11.5px] text-ink-faint">
                  已提交,等它跑起来…
                </span>
                <span v-else-if="queued" class="text-[11.5px] text-ink-faint">
                  排上了:跑完之后刷新就能看到这一轮。
                </span>
              </div>
            </form>
          </div>
        </section>

        <!-- 右栏 -->
        <div class="col-span-12 space-y-4 lg:col-span-4">
          <section class="panel overflow-hidden">
            <div class="flex items-center justify-between border-b border-line px-5 py-3.5">
              <h2 class="text-[13px] font-semibold">分支与 PR</h2>
              <span class="mono-label">THREAD</span>
            </div>
            <div class="space-y-2.5 p-5">
              <template v-if="data.branch">
                <div class="flex items-center gap-2">
                  <span class="mono-label w-14 shrink-0">分支</span>
                  <span class="truncate font-mono text-[12px] text-ink">{{ data.branch.head }}</span>
                </div>
                <div class="flex items-center gap-2">
                  <span class="mono-label w-14 shrink-0">PR</span>
                  <a
                    v-if="data.branch.url"
                    :href="data.branch.url"
                    target="_blank"
                    rel="noreferrer"
                    class="flex items-center gap-1.5 font-mono text-[12px] text-ink-soft transition-colors hover:text-ink"
                  >
                    #{{ data.branch.pull }}
                    <AppIcon name="external-link" :size="11" />
                  </a>
                  <span v-else class="font-mono text-[12px] text-ink-soft">#{{ data.branch.pull }}</span>
                </div>
                <div class="flex items-center gap-2">
                  <span class="mono-label w-14 shrink-0">仓库</span>
                  <span class="truncate font-mono text-[12px] text-ink-soft">{{ data.branch.repo }}</span>
                </div>
              </template>
              <p v-else class="text-[12px] leading-relaxed text-ink-soft">
                这个话题上还没有开着的 PR。前面的改动都在 comment 上,或者已经收尾了。
              </p>
            </div>
          </section>

          <section class="panel overflow-hidden">
            <div class="flex items-center justify-between border-b border-line px-5 py-3.5">
              <h2 class="text-[13px] font-semibold">变更单元</h2>
              <span class="mono-label">{{ conclusions.length }} UNITS</span>
            </div>
            <div v-if="conclusions.length" class="divide-y divide-line/50">
              <NuxtLink
                v-for="c in conclusions"
                :key="unitOf(c.seg)"
                :to="scopedTo('/changes')"
                class="flex items-start gap-3 px-5 py-3 transition-colors hover:bg-well/40"
              >
                <span class="mt-0.5 shrink-0 font-mono text-[11px] text-ink-faint">R{{ c.round }}</span>
                <span class="min-w-0 flex-1">
                  <span class="block truncate text-[12.5px] leading-snug text-ink-soft">
                    {{ c.seg.summary }}
                  </span>
                  <span class="mt-1 block truncate font-mono text-[11px] text-ink-faint">
                    {{ unitOf(c.seg) || '—' }}
                  </span>
                </span>
                <span class="chip shrink-0" :class="outcomeOf(c.seg).cls">
                  {{ outcomeOf(c.seg).label }}
                </span>
              </NuxtLink>
            </div>
            <p v-else class="px-5 py-4 text-[12px] text-ink-soft">这条线上还没有变更。</p>
          </section>

          <section class="panel overflow-hidden">
            <div class="flex items-center justify-between border-b border-line px-5 py-3.5">
              <h2 class="text-[13px] font-semibold">原始记录</h2>
              <span class="mono-label">RAW</span>
            </div>
            <div class="space-y-2 p-5">
              <div class="flex items-start gap-2">
                <span class="mono-label w-14 shrink-0 pt-0.5">话题</span>
                <span class="min-w-0 break-all font-mono text-[11.5px] text-ink-soft">{{ data.topic || '—' }}</span>
              </div>
              <div v-for="round in data.rounds" :key="round.key" class="flex items-start gap-2">
                <span class="mono-label w-14 shrink-0 pt-0.5">第 {{ round.round }} 轮</span>
                <span class="min-w-0 break-all font-mono text-[11.5px] text-ink-soft">{{ round.key || '—' }}</span>
              </div>
              <NuxtLink
                :to="scopedTo('/changes')"
                class="mt-1 inline-flex items-center gap-1.5 text-[11.5px] font-medium text-ink-faint transition-colors hover:text-ink"
              >
                <AppIcon name="scroll-text" :size="11" />
                去账本看这些单元的全部事件
              </NuxtLink>
            </div>
          </section>

          <PluginSlot
            slot="issue-detail.sidebar"
            hide-empty
            empty-hint="插件可以在这里补充这个议题的上下文。"
          />
        </div>
      </div>
    </template>
  </div>
</template>