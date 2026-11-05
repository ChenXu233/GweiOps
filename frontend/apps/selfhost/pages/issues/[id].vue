<script setup lang="ts">
import { useIssueDetail } from '@gwei/core/composables/useIssueDetail'

const route = useRoute()
const id = computed(() => String(route.params.id || ''))
const { data, loading, error } = useIssueDetail(id.value)

const selectedPatch = ref<string | null>(null)

watch(
  data,
  (v) => {
    if (!v) return
    // 引擎不给"默认选中"这种字段,选中状态完全由这里决定:默认第一条
    selectedPatch.value = v.patches[0]?.id ?? null
  },
  { immediate: true },
)

const typeLabel: Record<string, string> = {
  hotfix: '应急止血',
  proper: '根治',
  refactor: '重构',
  upstream: '上游升级',
  patch: '补丁',
  docs: '文档',
}

const riskLabel: Record<string, string> = { low: '低风险', medium: '中风险', high: '高风险' }

const riskCls: Record<string, string> = {
  low: 'chip-ok',
  medium: 'chip-warn',
  high: 'chip-bad',
}

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

function stepIndex(steps: string[], current: string) {
  const i = steps.indexOf(current)
  return i < 0 ? 0 : i
}
</script>

<template>
  <div class="space-y-5">
    <NuxtLink
      to="/issues"
      class="inline-flex items-center gap-1.5 text-[12px] font-medium text-ink-faint transition-colors hover:text-ink"
    >
      <AppIcon name="arrow-right" :size="13" class="rotate-180" />
      回到议题
    </NuxtLink>

    <div v-if="loading" class="space-y-3">
      <div class="h-8 w-2/3 animate-pulse rounded-lg bg-well" />
      <div class="h-4 w-1/3 animate-pulse rounded bg-well" />
    </div>

    <div v-else-if="error || !data" class="panel p-6">
      <p class="text-[13px] font-medium">找不到这个议题</p>
      <p class="mt-1 text-[12px] text-ink-soft">它可能已经完成并被归档。</p>
    </div>

    <template v-else>
      <header class="space-y-3">
        <div class="flex flex-wrap items-center gap-2">
          <span class="font-mono text-[11.5px] text-ink-faint">{{ data.id }}</span>
          <span class="chip" :class="statusCls[data.status]">
            {{ statusLabel[data.status] }}
          </span>
          <span class="chip font-mono text-[11.5px]">
            {{ sourceLabel[data.source] || data.source }}
          </span>
        </div>

        <h1 class="max-w-3xl text-[24px] font-semibold leading-tight tracking-tightest">
          {{ data.title }}
        </h1>

        <div class="flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-[11.5px] text-ink-faint">
          <span class="flex items-center gap-1.5"><AppIcon name="repos" :size="12" />{{ data.repo }}</span>
          <span class="flex items-center gap-1.5"><AppIcon name="clock" :size="12" />{{ data.triggeredAt }}</span>
          <span class="flex items-center gap-1.5"><AppIcon name="layers" :size="12" />{{ data.patches.length }} 个方案</span>
        </div>
      </header>

      <div class="grid grid-cols-12 items-start gap-4">
        <section class="panel col-span-12 lg:col-span-7">
          <div class="flex items-center justify-between border-b border-line px-5 py-3.5">
            <h2 class="text-[13px] font-semibold">候选方案</h2>
            <span class="mono-label">PATCHES</span>
          </div>

          <div class="space-y-2.5 p-4">
            <button
              v-for="p in data.patches"
              :key="p.id"
              class="w-full rounded-xl border p-4 text-left transition-colors"
              :class="selectedPatch === p.id
                ? 'border-ink/30 bg-well/60'
                : 'border-line hover:border-ink/20 hover:bg-well/30'"
              @click="selectedPatch = p.id"
            >
              <div class="flex items-center gap-2">
                <span
                  class="grid h-4 w-4 place-items-center rounded-full border transition-colors"
                  :class="selectedPatch === p.id ? 'border-ink bg-ink text-paper' : 'border-line text-transparent'"
                >
                  <AppIcon name="check" :size="9" :stroke="3" />
                </span>
                <span class="text-[13px] font-medium">{{ typeLabel[p.type] || p.type }}</span>
                <span class="chip px-1.5 text-[11px]" :class="riskCls[p.risk]">
                  {{ riskLabel[p.risk] }}
                </span>
                <span class="ml-auto font-mono text-[11.5px] text-ink-faint">{{ p.lines }} 行</span>
              </div>

              <p class="mt-2 pl-6 text-[12px] leading-relaxed text-ink-soft">{{ p.description }}</p>

              <div class="mt-2.5 flex gap-4 pl-6 font-mono text-[11.5px] text-ink-faint">
                <span>通过率 {{ p.passRate }}%</span>
                <span>延迟 {{ p.latency }}</span>
              </div>
            </button>

            <EmptyState
              v-if="!data.patches.length"
              icon="box"
              title="还没有生成方案"
              hint="诊断完成后,这里会出现多条可选路径及其风险。"
            />
          </div>
        </section>

        <div class="col-span-12 space-y-4 lg:col-span-5">
          <section class="panel">
            <div class="flex items-center justify-between border-b border-line px-5 py-3.5">
              <h2 class="text-[13px] font-semibold">金丝雀</h2>
              <span class="mono-label">CANARY</span>
            </div>

            <div v-if="data.canary" class="p-5">
              <div class="flex items-baseline justify-between">
                <span class="mono-label">当前流量</span>
                <span class="num font-mono text-[13px] font-semibold">{{ data.canary.current }}</span>
              </div>

              <div class="mt-4 flex items-center">
                <template v-for="(step, i) in data.canary.steps" :key="step">
                  <div class="flex flex-col items-center gap-1.5">
                    <span
                      class="grid h-6 w-6 place-items-center rounded-full text-[11px] font-semibold"
                      :class="
                        i < stepIndex(data.canary.steps, data.canary.current)
                          ? 'bg-ink text-paper'
                          : i === stepIndex(data.canary.steps, data.canary.current)
                            ? 'bg-brand text-white'
                            : 'border border-line text-ink-faint'
                      "
                    >
                      <AppIcon
                        v-if="i < stepIndex(data.canary.steps, data.canary.current)"
                        name="check"
                        :size="11"
                      />
                      <template v-else>{{ i + 1 }}</template>
                    </span>
                    <span
                      class="font-mono text-[9px] tracking-wider"
                      :class="i <= stepIndex(data.canary.steps, data.canary.current) ? 'text-ink-soft' : 'text-ink-faint'"
                    >{{ step }}</span>
                  </div>
                  <div
                    v-if="i < data.canary.steps.length - 1"
                    class="mb-4 h-px flex-1"
                    :class="i < stepIndex(data.canary.steps, data.canary.current) ? 'bg-ink/40' : 'bg-line'"
                  />
                </template>
              </div>

              <div class="mt-5 grid grid-cols-2 gap-px overflow-hidden rounded-tile bg-line">
                <div class="bg-panel px-3 py-2.5">
                  <div class="mono-label">通过率</div>
                  <div class="num mt-1 text-[15px] font-semibold">{{ data.canary.metrics.passRate }}%</div>
                </div>
                <div class="bg-panel px-3 py-2.5">
                  <div class="mono-label">错误率</div>
                  <div class="num mt-1 text-[15px] font-semibold">{{ data.canary.metrics.errorRate }}%</div>
                </div>
                <div class="bg-panel px-3 py-2.5">
                  <div class="mono-label">P99</div>
                  <div class="num mt-1 text-[15px] font-semibold">{{ data.canary.metrics.p99Latency }}</div>
                </div>
                <div class="bg-panel px-3 py-2.5">
                  <div class="mono-label">内存峰值</div>
                  <div class="num mt-1 text-[15px] font-semibold">{{ data.canary.metrics.memoryPeak }}</div>
                </div>
              </div>
            </div>

            <EmptyState
              v-else
              icon="activity"
              title="还没进入灰度"
              hint="选定方案后会按 1% → 10% → 50% → 100% 逐步放量。"
            />
          </section>

          <section class="panel">
            <div class="flex items-center justify-between border-b border-line px-5 py-3.5">
              <h2 class="text-[13px] font-semibold">时间线</h2>
              <span class="mono-label">TIMELINE</span>
            </div>

            <ol class="p-5">
              <li v-for="(step, i) in data.timeline" :key="step.id" class="relative flex items-center gap-3 pb-4 last:pb-0">
                <span
                  v-if="i < data.timeline.length - 1"
                  class="absolute left-[7px] top-4 h-full w-px"
                  :class="step.status === 'done' ? 'bg-ink/25' : 'bg-line'"
                />
                <span
                  class="relative z-10 grid h-[15px] w-[15px] shrink-0 place-items-center rounded-full border-2"
                  :class="step.status === 'done'
                    ? 'border-ink bg-ink'
                    : step.status === 'active'
                      ? 'border-brand bg-panel'
                      : 'border-line bg-panel'"
                >
                  <span v-if="step.status === 'active'" class="h-1.5 w-1.5 rounded-full bg-brand" />
                </span>
                <span
                  class="text-[12.5px]"
                  :class="step.status === 'pending'
                    ? 'text-ink-faint'
                    : step.status === 'active'
                      ? 'font-medium text-ink'
                      : 'text-ink-soft'"
                >
                  {{ step.label }}
                </span>
                <span v-if="step.status === 'active'" class="ml-auto font-mono text-[11px] text-brand">进行中</span>
              </li>
            </ol>
          </section>
        </div>
      </div>
    </template>
  </div>
</template>