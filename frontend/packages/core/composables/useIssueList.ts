import { ref } from 'vue'
import { IssuesApi } from '../api/client'
import { mockIssues } from '../mock'
import type { Issue } from '../types/issues'

const USE_MOCK = import.meta.env.NUXT_PUBLIC_USE_MOCK === 'true'

export function useIssueList() {
  const data = ref<Issue[]>([])
  const loading = ref(true)
  const error = ref<unknown>(null)

  async function fetch() {
    loading.value = true
    error.value = null
    try {
      data.value = USE_MOCK ? mockIssues : await IssuesApi.list()
    } catch (e) {
      error.value = e
    } finally {
      loading.value = false
    }
  }

  if (import.meta.client) fetch()

  return { data, loading, error, refresh: fetch }
}
