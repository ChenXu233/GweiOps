import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ObservabilityApi } from '../api/observability'
import { mockMetrics } from '../mock/observability'
import type { MetricGroup, MetricRow, MetricSample } from '../types/observability'

/** 自动重读的间隔。页面上的说明文字也用它,免得两处数字对不上。 */
export const OBSERVABILITY_POLL_MS = 15_000

/**
 * 组名 = 指标名里第一段下划线之前的部分。
 * gwei_llm_calls_total -> gwei;没有下划线就用整名。
 */
export function metricPrefix(name: string): string {
  const cut = name.indexOf('_')
  return cut > 0 ? name.slice(0, cut) : name
}

/** 标签签名:键排序后拼成 key=value,用来排序和做稳定 key。 */
function labelSignature(labels: Record<string, string>): string {
  return Object.keys(labels)
    .sort()
    .map((k) => k + '=' + labels[k])
    .join(',')
}

/**
 * 把扁平序列摊成"分组 → 行"。
 *
 * 分组按指标名前缀;同一组里按指标名、标签签名排序,所以顺序稳定可预期。
 * 每一行的 delta 是它减去同组同名序列里上一条的值——也就是"同类上一条"的口径。
 * 只有一条的同类没有可比对象,delta 为 null。
 */
export function groupMetrics(samples: MetricSample[]): MetricGroup[] {
  const sorted = [...samples].sort((a, b) => {
    if (a.name !== b.name) return a.name < b.name ? -1 : 1
    const sa = labelSignature(a.labels)
    const sb = labelSignature(b.labels)
    return sa < sb ? -1 : sa > sb ? 1 : 0
  })

  const familySize = new Map<string, number>()
  for (const s of sorted) {
    const family = s.name
    familySize.set(family, (familySize.get(family) ?? 0) + 1)
  }

  const groups = new Map<string, MetricRow[]>()
  const lastOfFamily = new Map<string, number>()

  for (const s of sorted) {
    const prefix = metricPrefix(s.name)
    const previous = lastOfFamily.get(s.name)
    const rows = groups.get(prefix) ?? []
    rows.push({
      name: s.name,
      labels: s.labels,
      value: s.value,
      key: s.name + '{' + labelSignature(s.labels) + '}',
      prefix,
      familySize: familySize.get(s.name) ?? 1,
      previousValue: previous === undefined ? null : previous,
      delta: previous === undefined ? null : s.value - previous,
    })
    lastOfFamily.set(s.name, s.value)
    groups.set(prefix, rows)
  }

  return [...groups.entries()].map(([prefix, rows]) => ({
    prefix,
    rows,
    families: new Set(rows.map((r) => r.name)).size,
  }))
}

/**
 * 指标观测:拉一次引擎当前的指标快照。
 * 每 15 秒重读一次;mock 模式下重读到的还是那批固定的演示值。
 */
export function useObservability() {
  const useMock = useRuntimeConfig().public.useMock === true

  const samples = ref<MetricSample[]>([])
  const loading = ref(true)
  const refreshing = ref(false)
  const error = ref<string | null>(null)
  const fetchedAt = ref<Date | null>(null)

  let inflight = false

  async function load(silent: boolean) {
    if (inflight) return
    inflight = true
    if (!silent) refreshing.value = true
    error.value = null
    try {
      // mock 分支也走一次 await,让"读取中"这一帧真的画得出来
      const rows = useMock ? await Promise.resolve(mockMetrics) : await ObservabilityApi.list()
      samples.value = rows
      fetchedAt.value = new Date()
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
    } finally {
      inflight = false
      loading.value = false
      if (!silent) refreshing.value = false
    }
  }

  /** 手动刷新:有按钮转圈的反馈。 */
  function refresh() {
    return load(false)
  }

  const groups = computed(() => groupMetrics(samples.value))
  const total = computed(() => samples.value.length)
  const groupCount = computed(() => groups.value.length)

  let timer: ReturnType<typeof setInterval> | null = null

  onMounted(() => {
    refresh()
    timer = setInterval(() => load(true), OBSERVABILITY_POLL_MS)
  })

  onUnmounted(() => {
    if (timer) clearInterval(timer)
  })

  return { samples, groups, total, groupCount, loading, refreshing, error, fetchedAt, refresh }
}
