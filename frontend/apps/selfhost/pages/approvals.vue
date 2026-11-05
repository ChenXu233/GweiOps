<script setup lang="ts">
import { blockReasonOf, useApprovals } from '@gwei/core/composables/useApprovals'
import type { ApprovalAction, ApprovalItem } from '@gwei/core/types/approvals'
import type { Tone } from '@gwei/core/utils/tone'

const { items, total, loading, error, actingId, actingAction, failure, notice, groups, refresh, approve, veto } =
  useApprovals()

/** 页首那排数字:待放行总数,再加按阻断原因拆开的条数。 */
const overview = computed(() => [
  { label: '待放行', value: total.value, hint: '停在账本里等人点头的改变' },
  ...groups.value.map((g) => ({ label: g.label, value: g.count })),
])

/** 二次确认:一次点击只是"把手放在按钮上",再点一次才算。 */
const confirming = ref<{ id: string; action: ApprovalAction } | null>(null)

const toneChip: Record<Tone, string> = {
  ok: 'chip-ok',
  warn: 'chip-warn',
  bad: 'chip-bad',
  info: 'chip-info',
  idle: '',
}

function when(iso: string) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso.slice(0, 19).replace('T', ' ')
  const p = (n: number) => String(n).padStart(2, '0')
  return p(d.getMonth() + 1) + '-' + p(d.getDate()) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes())
}

function fields(row: ApprovalItem) {
  return [
    { k: '能力', v: row.effect?.capability || '—' },
    { k: '提供者任务', v: row.effect?.task || '—' },
    { k: '幂等键', v: row.idempotency_key || '—' },
  ]
}

function isConfirming(row: ApprovalItem, action: ApprovalAction) {
  return confirming.value?.id === row.id && confirming.value.action === action
}

function onAct(row: ApprovalItem, action: ApprovalAction) {
  if (actingId.value) return
  if (isConfirming(row, action)) {
    confirming.value = null
    void (action === 'approve' ? approve(row.id) : veto(row.id))
    return
  }
  confirming.value = { id: row.id, action }
}

function approveLabel(row: ApprovalItem) {
  if (actingId.value === row.id && actingAction.value === 'approve') return '放行中…'
  if (isConfirming(row, 'approve')) return '再点一次确认放行'
  return '放行'
}

function vetoLabel(row: ApprovalItem) {
  if (actingId.value === row.id && actingAction.value === 'veto') return '否决中…'
  if (isConfirming(row, 'veto')) return '再点一次确认否决'
  return '否决'
}

// 确认态停留太久就自己退回去,免得按钮一直举着"待确认"的姿势。
let confirmTimer: ReturnType<typeof setTimeout> | null = null
watch(confirming, (next) => {
  if (confirmTimer) {
    clearTimeout(confirmTimer)
    confirmTimer = null
  }
  if (next && import.meta.client) {
    confirmTimer = setTimeout(() => {
      confirming.value = null
    }, 6000)
  }
})
onUnmounted(() => {
  if (confirmTimer) clearTimeout(confirmTimer)
})
</script>

<template>
  <div class="space-y-5">
    <PageHeader
      eyebrow="待放行"
      title="需要人点头的改变"
      description="夜里那些不可逆或被策略拦下的改变停在账本里,等人点头。放行与否都会写回账本。"
    >
      <template #actions>
        <button class="btn-outline btn-sm" :disabled="loading" @click="refresh()">
          <AppIcon name="refresh" :size="13" :class="loading ? 'animate-spin' : ''" />
          刷新
        </button>
      </template>
    </PageHeader>

    <!-- 概览:待放行总数 + 阻断原因归类 -->
    <StatBand :columns="4" :stats="overview" />

    <p v-if="groups.length" class="text-[12px] leading-relaxed text-ink-faint">
      归类是我们照引擎写下的原因文本读出来的,不是引擎给的字段。
    </p>

    <!-- 读不到队列 -->
    <div
      v-if="error"
      class="rounded-card border border-coral/30 bg-coral/5 p-4 text-[12.5px] text-coral"
    >
      <div class="flex items-start gap-2">
        <AppIcon name="alert" :size="15" class="mt-px shrink-0" />
        <div class="min-w-0">
          <div class="font-medium">读不到待放行队列</div>
          <p class="mt-1 break-words leading-relaxed">{{ error }}</p>
        </div>
      </div>
    </div>

    <!-- 放行/否决失败:把引擎给的原因摆出来,不做静默 -->
    <div
      v-if="failure"
      class="rounded-card border border-coral/30 bg-coral/5 p-4 text-[12.5px] text-coral"
    >
      <div class="flex items-start gap-2">
        <AppIcon name="alert" :size="15" class="mt-px shrink-0" />
        <div class="min-w-0">
          <div class="font-medium">
            {{ failure.action === 'approve' ? '这次放行没有生效' : '这次否决没有生效' }}
          </div>
          <p class="mt-1 leading-relaxed">{{ failure.message }}</p>
          <p class="mt-1.5 text-[12px] opacity-80">
            这条还在队列里,状态没有变
            <span v-if="failure.status" class="num">(引擎返回 {{ failure.status }})</span>
          </p>
        </div>
      </div>
    </div>

    <!-- 回执 -->
    <div
      v-if="notice"
      class="rounded-card border border-ok/25 bg-ok/10 p-4 text-[12.5px] text-ok"
    >
      <div class="flex items-start gap-2">
        <AppIcon name="check-circle" :size="15" class="mt-px shrink-0" />
        <p class="leading-relaxed">{{ notice.text }}</p>
      </div>
    </div>

    <!-- 骨架 -->
    <div v-if="loading && !items.length" class="space-y-3">
      <div v-for="i in 3" :key="i" class="panel space-y-3 p-4 sm:p-5">
        <div class="skeleton h-3 w-28" />
        <div class="skeleton h-4 w-2/3" />
        <div class="skeleton h-16 w-full" />
      </div>
    </div>

    <!-- 空态 -->
    <div v-else-if="!items.length" class="panel">
      <EmptyState
        icon="shield-check"
        title="没有需要人点头的改变"
        hint="夜里引擎做的改变都自己走完了流程,或者已经有人处理过。下一次有改变停下来时,它会出现在这里。"
      />
    </div>

    <!-- 队列 -->
    <div v-else class="space-y-3">
      <article
        v-for="row in items"
        :key="row.id"
        class="panel panel-lift p-4 sm:p-5"
        :class="failure?.id === row.id ? 'border-coral/40' : ''"
      >
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div class="min-w-0 flex-1">
            <div class="flex flex-wrap items-center gap-1.5">
              <span class="chip" :class="toneChip[blockReasonOf(row).tone]">
                {{ blockReasonOf(row).label }}
              </span>
              <span class="chip">{{ row.binding || '未绑定' }}</span>
              <span class="chip">{{ row.tenant || '未指定租户' }}</span>
            </div>
            <h2 class="mt-2.5 text-balance text-[15px] font-semibold leading-snug">
              {{ row.intent?.summary || '(引擎没有写摘要)' }}
            </h2>
            <p class="mt-1 truncate font-mono text-[11.5px] text-ink-faint">{{ row.id }}</p>
          </div>
          <div class="flex shrink-0 items-center gap-1.5 text-[12px] text-ink-faint">
            <AppIcon name="clock" :size="13" />
            <span class="num font-mono">{{ when(row.created_at) }}</span>
          </div>
        </div>

        <dl
          class="mt-4 grid gap-x-6 gap-y-2.5 border-t border-line/70 pt-4 sm:grid-cols-2"
        >
          <div v-for="f in fields(row)" :key="f.k" class="flex min-w-0 items-baseline gap-2">
            <dt class="w-20 shrink-0 text-[12px] text-ink-faint">{{ f.k }}</dt>
            <dd class="min-w-0 flex-1 truncate font-mono text-[12px] text-ink-soft" :title="f.v">
              {{ f.v }}
            </dd>
          </div>
        </dl>

        <div class="panel-inset mt-4 p-3.5">
          <div class="mono-label">为什么停在这里</div>
          <p class="mt-1.5 text-[12.5px] leading-relaxed text-ink-soft">
            {{ row.reason || '引擎没有写原因' }}
          </p>
        </div>

        <p class="mt-4 flex items-start gap-1.5 text-[12px] leading-relaxed text-ink-faint">
          <AppIcon name="shield-check" :size="13" class="mt-0.5 shrink-0" />
          <span>放行 = 此刻有人在场。执行后照样读窗口、照样验证,验证不过照样回滚。</span>
        </p>

        <div class="mt-3.5 flex flex-wrap items-center gap-2 border-t border-line/70 pt-3.5">
          <button
            class="btn btn-solid"
            :disabled="Boolean(actingId)"
            @click="onAct(row, 'approve')"
          >
            <AppIcon
              :name="actingId === row.id && actingAction === 'approve' ? 'loader' : 'check'"
              :size="14"
              :class="actingId === row.id && actingAction === 'approve' ? 'animate-spin' : ''"
            />
            {{ approveLabel(row) }}
          </button>
          <button
            class="btn btn-danger"
            :disabled="Boolean(actingId)"
            @click="onAct(row, 'veto')"
          >
            <AppIcon
              :name="actingId === row.id && actingAction === 'veto' ? 'loader' : 'x'"
              :size="14"
              :class="actingId === row.id && actingAction === 'veto' ? 'animate-spin' : ''"
            />
            {{ vetoLabel(row) }}
          </button>
          <span v-if="confirming?.id === row.id" class="text-[12px] text-ink-faint">
            再点一次「{{ confirming.action === 'approve' ? '放行' : '否决' }}」以确认。
          </span>
        </div>
      </article>
    </div>
  </div>
</template>