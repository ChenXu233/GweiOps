// packages/core/composables/useChanges.ts
import { onMounted, ref } from 'vue'
import { ChangesApi } from '../api/client'
import type { ChangeRow } from '../types/changes'

export function useChanges() {
  const items = ref<ChangeRow[]>([])
  const total = ref(0)
  const loading = ref(true)
  const error = ref<string | null>(null)
  const rollingBack = ref<string | null>(null)

  async function refresh(verdict?: string) {
    loading.value = true
    error.value = null
    try {
      const data = await ChangesApi.list({ verdict, limit: 200 })
      items.value = data.items
      total.value = data.total
    }
    catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
    }
    finally {
      loading.value = false
    }
  }

  async function rollback(id: string) {
    rollingBack.value = id
    error.value = null
    try {
      await ChangesApi.rollback(id, '人工回滚')
      await refresh()
    }
    catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
    }
    finally {
      rollingBack.value = null
    }
  }

  onMounted(() => refresh())

  return { items, total, loading, error, rollingBack, refresh, rollback }
}
