<script setup lang="ts">
import { OBSERVABILITY_POLL_MS, useObservability } from '@gwei/core/composables/useObservability'
import type { MetricRow } from '@gwei/core/types/observability'

const { groups, total, groupCount, loading, refreshing, error, fetchedAt, refresh } = useObservability()

const pollText = `每 ${Math.round(OBSERVABILITY_POLL_MS / 1000)} 秒重读一次`

const snapshotTime = computed(() => {
  const at = fetchedAt.value
  if (!at) return '—'
  const p = (n: number) => String(n).padStart(2, '0')
  return p(at.getHours()) + ':' + p(at.getMinutes()) + ':' + p(at.getSeconds())
})

/** 页首那排数字。口径和页面正文一致,不在这里额外加工。 */
const overview = computed(() => [
  {
    label: '指标序列',
    value: total.value,
    hint: '收集器里当前存在的每一条时间序列,同名不同标签算两条。',
  },
  {
    label: '分组',
    value: groupCount.value,
    hint: '按指标名的前缀归堆,同堆的放在一起看。',
  },
  {
    label: '快照',
    value: snapshotTime.value,
    hint: '这是引擎当前的快照,不是时间序列——刷新一次就是一次新的读数。',
  },
])

/** 大数用千分位,小数保留到能看清差异的位数。 */
function formatValue(value: number): string {
  if (!Number.isFinite(value)) return '—'
  if (Number.isInteger(value)) return value.toLocaleString('en-US')
  const abs = Math.abs(value)
  const digits = abs >= 1000 ? 1 : abs >= 1 ? 3 : 6
  return value.toLocaleString('en-US', { maximumFractionDigits: digits })
}

function formatDelta(delta: number): string {
  if (delta === 0) return '±0'
  return (delta > 0 ? '+' : '−') + formatValue(Math.abs(delta))
}

function sortedLabels(row: MetricRow): Array<[string, string]> {
  const out: Array<[string, string]> = []
  for (const key of Object.keys(row.labels).sort()) out.push([key, row.labels[key]])
  return out
}
</script>

<template>
  <div class="space-y-5">
    <PageHeader
      eyebrow="OBSERVABILITY"
      title="指标观测"
      description="引擎、插件和 LLM 计量写进收集器的当前值,摊开就是引擎此刻的样子。"
    >
      <template #actions>
        <span class="eyebrow hidden sm:inline">{{ total }} 序列 · {{ groupCount }} 组</span>
        <button class="btn-outline btn-sm" :disabled="refreshing" @click="refresh">
          <AppIcon name="refresh" :size="13" :class="refreshing ? 'animate-spin' : ''" />
          {{ refreshing ? '读取中…' : '刷新' }}
        </button>
      </template>
    </PageHeader>

    <StatBand :columns="3" :stats="overview" />

    <p class="text-[11.5px] leading-relaxed text-ink-faint">
      分组按指标名前缀;“变化”是同名指标里这一条减去上一条序列的差值,只有一条序列的指标没有可比对象。
    </p>

    <div v-if="error" class="panel border-coral/30 bg-coral/5 p-4">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <p class="text-[12.5px] text-coral">拉不到指标快照:{{ error }}</p>
        <button class="btn-outline btn-sm" :disabled="refreshing" @click="refresh">
          <AppIcon name="refresh" :size="13" :class="refreshing ? 'animate-spin' : ''" />
          重试
        </button>
      </div>
    </div>

    <div v-if="loading && !groups.length" class="space-y-4">
      <div v-for="i in 3" :key="i" class="h-[200px] skeleton" />
    </div>

    <template v-else-if="groups.length">
      <section v-for="group in groups" :key="group.prefix" class="panel overflow-hidden">
        <div
          class="flex flex-wrap items-center justify-between gap-2 border-b border-line px-5 py-3.5"
        >
          <div class="flex min-w-0 items-center gap-2.5">
            <AppIcon name="layers" :size="15" class="text-ink-faint" />
            <h2 class="font-mono text-[13px] font-semibold">{{ group.prefix }}</h2>
            <span class="chip">{{ group.rows.length }} 个序列</span>
          </div>
          <span class="eyebrow">{{ group.families }} 类指标</span>
        </div>

        <div class="max-h-[440px] overflow-y-auto">
          <div
            class="hidden grid-cols-12 gap-3 border-b border-line/70 bg-well/40 px-5 py-2 sm:grid"
          >
            <div class="col-span-5 eyebrow">指标</div>
            <div class="col-span-3 eyebrow">标签</div>
            <div class="col-span-2 eyebrow text-right">当前值</div>
            <div class="col-span-2 eyebrow text-right" title="同名指标里这一条减去上一条序列的差值">
              变化
            </div>
          </div>

          <div
            v-for="row in group.rows"
            :key="row.key"
            class="grid grid-cols-12 items-center gap-x-3 gap-y-1.5 border-b border-line/60 px-5 py-2.5 transition-colors last:border-0 hover:bg-well/40"
          >
            <div class="col-span-12 min-w-0 sm:col-span-5">
              <span class="break-all font-mono text-[12px] text-ink">{{ row.name }}</span>
            </div>

            <div class="col-span-12 flex flex-wrap gap-1.5 sm:col-span-3">
              <template v-if="Object.keys(row.labels).length">
                <span v-for="[key, value] in sortedLabels(row)" :key="key" class="chip">
                  {{ key }}={{ value }}
                </span>
              </template>
              <span v-else class="chip text-ink-faint">无标签</span>
            </div>

            <div class="col-span-6 flex items-baseline gap-2 sm:col-span-2 sm:justify-end">
              <span class="num text-[14px] font-semibold leading-none">{{ formatValue(row.value) }}</span>
            </div>

            <div class="col-span-6 flex items-baseline sm:col-span-2 sm:justify-end">
              <span
                v-if="row.delta !== null"
                class="num text-[11.5px] text-ink-soft"
                :title="'上一条同类序列的值是 ' + formatValue(row.previousValue ?? 0)"
              >
                {{ formatDelta(row.delta) }}
              </span>
              <span v-else-if="row.familySize > 1" class="text-[11.5px] text-ink-faint">—</span>
            </div>
          </div>
        </div>
      </section>
    </template>

    <EmptyState
      v-else-if="!error"
      icon="observability"
      title="引擎还没上报指标"
      hint="引擎跑起来、插件往收集器写进第一条之后,这里立刻就会出现读数。"
    />
  </div>
</template>