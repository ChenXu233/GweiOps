<script setup lang="ts">
import { useDashboard } from '@gwei/core/composables/useDashboard'
import { usePluginWidgets } from '@gwei/core/composables/usePluginWidgets'

const { data, pendingIssues, overnightEvents, canaryStatuses, loading, error, refresh } =
  useDashboard()
const { widgets: pluginWidgets } = usePluginWidgets('dashboard.bento')

const statusText: Record<string, string> = {
  healthy: '稳定运行',
  warning: '需要留意',
  critical: '故障中',
}

const metrics = computed(() => {
  const d = data.value
  if (!d) return []
  return [
    { label: 'MTTR', value: d.mttr, unit: 'min', icon: 'timer' },
    { label: '修复成功率', value: d.successRate, unit: '%', icon: 'trending-up' },
    { label: '记忆条目', value: d.memoryEntries, unit: '条', icon: 'database' },
    { label: '活跃执行体', value: d.activeAgents, unit: '个', icon: 'cpu' },
  ]
})

// 过去 N 天的健康轨迹:true = 当天无事故。
// 折线比色块更容易看出"哪天掉下去了"——平的那段就是没出事的那段。
const health = computed(() => {
  const values = data.value?.healthHistory ?? []
  if (values.length < 2) return null

  const n = values.length
  const pad = 2
  const xFor = (i: number) => pad + (i / (n - 1)) * (100 - pad * 2)
  const yFor = (ok: boolean) => (ok ? 14 : 84)

  const pts = values.map((ok, i) => ({ x: xFor(i), y: yFor(ok), ok }))
  const line = pts
    .map((pt, i) => (i === 0 ? 'M' : 'L') + pt.x.toFixed(2) + ' ' + pt.y.toFixed(2))
    .join(' ')
  const first = pts.findIndex(pt => !pt.ok)

  return {
    line,
    incident: first >= 0 ? pts[first] : null,
    incidentCount: values.filter(v => !v).length,
  }
})

function severityBar(severity: string) {
  if (severity === 'critical') return 'bg-coral'
  if (severity === 'medium') return 'bg-amber'
  return 'bg-ink-faint'
}

const issueStatusLabel: Record<string, string> = {
  pending_review: '待审',
  canary: '金丝雀',
  approved: '已放行',
  completed: '已完成',
  rolled_back: '已回滚',
}

const issueStatusClass: Record<string, string> = {
  pending_review: 'chip-warn',
  canary: 'chip-info',
  approved: 'chip-ok',
  completed: 'chip-ok',
  rolled_back: '',
}

function stepIndex(steps: string[], current: string) {
  const i = steps.indexOf(current)
  return i < 0 ? 0 : i
}
</script>

<template>
  <div class="space-y-5">
    <PageHeader eyebrow="CONTROL ROOM" title="控制室" description="夜里发生的事，早上只做判断。">
      <template #actions>
        <StatusPip tone="ok" pulse label="实时同步" />
        <button class="btn-outline btn-sm" :disabled="loading" @click="refresh">
          <AppIcon name="refresh" :size="13" :class="loading ? 'animate-spin' : ''" />
          刷新
        </button>
      </template>
    </PageHeader>

    <div v-if="loading && !data" class="grid grid-cols-12 gap-4">
      <div class="col-span-12 h-64 skeleton lg:col-span-7" />
      <div class="col-span-12 grid gap-4 lg:col-span-5">
        <div class="h-[122px] skeleton" />
        <div class="h-[122px] skeleton" />
      </div>
    </div>

    <div v-else-if="error" class="panel border-coral/30 bg-coral/5 p-6">
      <div class="flex items-center gap-2 text-[13px] font-medium text-coral">
        <AppIcon name="alert" :size="15" />
        拉不到控制室数据
      </div>
      <p class="mt-1.5 text-[12px] text-ink-soft">
        确认引擎在跑(NUXT_ENGINE_URL)，或者用 NUXT_PUBLIC_USE_MOCK=true 看演示数据。
      </p>
      <button class="btn-outline btn-sm mt-4" @click="refresh">重试</button>
    </div>

    <template v-else-if="data">
      <div class="grid grid-cols-12 gap-4">
        <!-- 主色块:系统态势 -->
        <section
          class="relative col-span-12 flex flex-col justify-between overflow-hidden rounded-panel bg-lime p-6 text-lime-ink lg:col-span-7"
        >

          <div class="relative flex items-start justify-between">
            <span class="font-mono text-[10px] uppercase tracking-[0.16em] text-lime-ink/55">系统态势</span>
            <span
              class="rounded-full border border-lime-ink/15 px-2 py-0.5 font-mono text-[10px] tracking-wider text-lime-ink/60"
            >
              {{ data.status.toUpperCase() }}
            </span>
          </div>

          <div class="relative mt-6">
            <h2 class="text-[38px] font-semibold leading-none tracking-tightest">
              {{ statusText[data.status] }}
            </h2>
            <p class="mt-2.5 text-[13px] text-lime-ink/65">
              连续 {{ data.consecutiveDays }} 天无事故<template v-if="data.lastIncident"> · 上次事故 {{ data.lastIncident }}</template>
            </p>
          </div>

          <div v-if="health" class="relative mt-7">
            <div class="relative h-16">
              <svg
                class="absolute inset-0 h-full w-full"
                viewBox="0 0 100 100"
                preserveAspectRatio="none"
                aria-hidden="true"
              >
                <path
                  :d="health.line"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="1.5"
                  stroke-opacity="0.7"
                  vector-effect="non-scaling-stroke"
                  stroke-linejoin="round"
                  stroke-linecap="round"
                />
              </svg>
              <span
                v-if="health.incident"
                class="absolute h-2 w-2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-lime-ink ring-[3px] ring-lime"
                :style="{ left: health.incident.x + '%', top: health.incident.y + '%' }"
              />
            </div>
            <div
              class="mt-2.5 flex items-baseline justify-between font-mono text-[10px] tracking-wider text-lime-ink/45"
            >
              <span>近 {{ data.healthHistory.length }} 天</span>
              <span v-if="health.incidentCount" class="text-lime-ink/60">{{ health.incidentCount }} 天异常</span>
              <span>今天</span>
            </div>
          </div>
        </section>

        <div class="col-span-12 grid gap-4 lg:col-span-5 lg:grid-rows-2">
          <NuxtLink
            to="/issues"
            class="group flex flex-col justify-between rounded-panel border border-amber/30 bg-amber/10 p-5 transition-colors hover:bg-amber/[0.16]"
          >
            <div class="flex items-center justify-between">
              <span class="font-mono text-[10px] uppercase tracking-[0.16em] text-amber">等你判断</span>
              <AppIcon
                name="arrow-up-right"
                :size="15"
                class="text-amber transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5"
              />
            </div>
            <div class="mt-5 flex items-baseline gap-2.5">
              <span class="num text-[34px] font-semibold leading-none tracking-tightest text-amber">
                {{ data.pendingReview }}
              </span>
              <span class="text-[12px] leading-tight text-ink-soft">件事已经做完，只差一个人点头</span>
            </div>
          </NuxtLink>

          <div class="relative flex flex-col justify-between overflow-hidden rounded-panel bg-solid p-5 text-solid-ink">
            <div
              class="pointer-events-none absolute inset-x-0 top-0 h-24 bg-gradient-to-b from-white/[0.07] to-transparent"
            />
            <div class="flex items-center justify-between">
              <span class="font-mono text-[10px] uppercase tracking-[0.16em] text-solid-ink/45">昨夜自动修复</span>
              <AppIcon name="moon" :size="15" class="text-solid-ink/40" />
            </div>
            <div class="mt-5 flex items-baseline gap-2.5">
              <span class="num text-[34px] font-semibold leading-none tracking-tightest">
                {{ data.overnightFixed }}
              </span>
              <span class="text-[12px] leading-tight text-solid-ink/50">件在你睡觉时完成并验证</span>
            </div>
          </div>
        </div>

        <StatBand class="col-span-12" :columns="4" :stats="metrics" />

        <section class="panel col-span-12 overflow-hidden lg:col-span-7">
          <div class="flex items-center justify-between border-b border-line px-5 py-3.5">
            <h2 class="text-[13px] font-semibold">待你判断</h2>
            <NuxtLink
              to="/issues"
              class="flex items-center gap-1 text-[12px] text-ink-faint transition-colors hover:text-ink"
            >
              全部
              <AppIcon name="arrow-right" :size="12" />
            </NuxtLink>
          </div>

          <ul v-if="pendingIssues.length" class="divide-y divide-line/70">
            <li v-for="item in pendingIssues" :key="item.id">
              <NuxtLink
                :to="'/issues/' + encodeURIComponent(item.id)"
                class="group flex items-center gap-3.5 px-5 py-3.5 transition-colors hover:bg-well/60"
              >
                <span class="h-7 w-[3px] shrink-0 rounded-full" :class="severityBar(item.severity)" />
                <div class="min-w-0 flex-1">
                  <div class="truncate text-[13px] font-medium">{{ item.title }}</div>
                  <div class="mt-1 font-mono text-[11px] text-ink-faint">
                    {{ item.id }} · {{ item.patchCount }} 个方案
                  </div>
                </div>
                <span
                  class="chip shrink-0"
                  :class="issueStatusClass[item.status]"
                >
                  {{ issueStatusLabel[item.status] }}
                </span>
                <AppIcon
                  name="chevron-right"
                  :size="14"
                  class="text-ink-faint opacity-0 transition-opacity group-hover:opacity-100"
                />
              </NuxtLink>
            </li>
          </ul>

          <EmptyState
            v-else
            icon="check-circle"
            title="没有待审条目"
            hint="夜里发生的改变都已经落在可回滚状态，醒来不需要做任何判断。"
          />
        </section>

        <section class="panel col-span-12 overflow-hidden lg:col-span-5">
          <div class="flex items-center justify-between border-b border-line px-5 py-3.5">
            <h2 class="text-[13px] font-semibold">金丝雀</h2>
            <span class="eyebrow">CANARY</span>
          </div>

          <div v-for="c in canaryStatuses" :key="c.issueId" class="p-5">
            <div class="flex items-baseline justify-between gap-3">
              <span class="truncate text-[13px] font-medium">{{ c.issueTitle }}</span>
              <span class="shrink-0 font-mono text-[11px] text-ink-faint">{{ c.issueId }}</span>
            </div>

            <div class="mt-4 flex items-center">
              <template v-for="(step, i) in c.steps" :key="step">
                <div class="flex flex-col items-center gap-1.5">
                  <span
                    class="grid h-6 w-6 place-items-center rounded-full text-[10px] font-semibold"
                    :class="
                      i < stepIndex(c.steps, c.currentStep)
                        ? 'bg-ink text-paper'
                        : i === stepIndex(c.steps, c.currentStep)
                          ? 'bg-brand text-white'
                          : 'border border-line text-ink-faint'
                    "
                  >
                    <AppIcon v-if="i < stepIndex(c.steps, c.currentStep)" name="check" :size="11" />
                    <template v-else>{{ i + 1 }}</template>
                  </span>
                  <span
                    class="font-mono text-[9px] tracking-wider"
                    :class="i <= stepIndex(c.steps, c.currentStep) ? 'text-ink-soft' : 'text-ink-faint'"
                  >{{ step }}</span>
                </div>
                <div
                  v-if="i < c.steps.length - 1"
                  class="mb-4 h-px flex-1"
                  :class="i < stepIndex(c.steps, c.currentStep) ? 'bg-ink/40' : 'bg-line'"
                />
              </template>
            </div>

            <div class="mt-5 grid grid-cols-2 gap-px overflow-hidden rounded-tile bg-line">
              <div class="bg-panel px-3 py-2.5">
                <div class="eyebrow">通过率</div>
                <div class="num mt-1 text-[15px] font-semibold">{{ c.metrics.passRate }}%</div>
              </div>
              <div class="bg-panel px-3 py-2.5">
                <div class="eyebrow">错误率</div>
                <div class="num mt-1 text-[15px] font-semibold">{{ c.metrics.errorRate }}%</div>
              </div>
              <div class="bg-panel px-3 py-2.5">
                <div class="eyebrow">P99</div>
                <div class="num mt-1 text-[15px] font-semibold">{{ c.metrics.p99Latency }}</div>
              </div>
              <div class="bg-panel px-3 py-2.5">
                <div class="eyebrow">内存峰值</div>
                <div class="num mt-1 text-[15px] font-semibold">{{ c.metrics.memoryPeak }}</div>
              </div>
            </div>
          </div>

          <EmptyState
            v-if="!canaryStatuses.length"
            icon="activity"
            title="没有进行中的金丝雀"
            hint="有变更进入灰度时，这里会显示每一步的实时指标。"
          />
        </section>

        <section class="panel col-span-12 overflow-hidden lg:col-span-7">
          <div class="flex items-center justify-between border-b border-line px-5 py-3.5">
            <h2 class="text-[13px] font-semibold">昨夜回顾</h2>
            <span class="eyebrow">NIGHT SHIFT</span>
          </div>

          <ol v-if="overnightEvents.length" class="divide-y divide-line/70">
            <li v-for="(e, i) in overnightEvents" :key="i" class="flex gap-3.5 px-5 py-3.5">
              <span class="mt-0.5 shrink-0 font-mono text-[11px] text-ink-faint">{{ e.time }}</span>
              <span
                class="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full"
                :class="e.result === 'success' ? 'bg-ok' : 'bg-coral'"
              />
              <div class="min-w-0">
                <div class="text-[13px] font-medium">{{ e.title }}</div>
                <div class="mt-1 text-[12px] leading-relaxed text-ink-soft">{{ e.description }}</div>
              </div>
            </li>
          </ol>

          <EmptyState v-else icon="moon" title="昨夜无事" hint="没有信号需要处理。" />
        </section>

        <div class="col-span-12 space-y-4 lg:col-span-5">
          <section
            v-for="w in pluginWidgets"
            :key="w.plugin + w.title"
            class="panel overflow-hidden"
          >
            <PluginWidget :widget="w" />
          </section>

          <section
            v-if="!pluginWidgets.length"
            class="rounded-panel border border-dashed border-line bg-panel/40 px-5 py-8 text-center"
          >
            <p class="text-[12px] text-ink-faint">插件可以往这里放自己的卡片。</p>
          </section>
        </div>
      </div>
    </template>
  </div>
</template>