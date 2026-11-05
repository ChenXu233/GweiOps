import { onMounted, ref } from 'vue'
import { RunsApi } from '../api/runs'
import { mockRuns } from '../mock/runs'
import type { RunRow } from '../types/runs'

export function useRuns() {
  const useMock = useRuntimeConfig().public.useMock === true
  const items = ref<RunRow[]>([])
  const total = ref(0)
  const loading = ref(true)
  const error = ref<string | null>(null)

  async function refresh() {
    loading.value = true
    error.value = null
    try {
      if (useMock) {
        items.value = mockRuns
        total.value = mockRuns.length
        return
      }
      const data = await RunsApi.list({ limit: 200 })
      items.value = data.items
      total.value = data.total
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
    } finally {
      loading.value = false
    }
  }

  if (useMock) {
    // mock 模式直接给数据,首屏不用等一拍
    items.value = mockRuns
    total.value = mockRuns.length
    loading.value = false
  } else {
    onMounted(() => refresh())
  }

  return { items, total, loading, error, refresh }
}
