import { ref } from 'vue'
import { IssuesApi } from '../api/client'
import { mockIssues } from '../mock'
import type { Issue } from '../types/issues'

export function useIssueList() {
  const useMock = useRuntimeConfig().public.useMock === true
  const data = ref<Issue[]>([])
  const loading = ref(true)
  const error = ref<unknown>(null)

  async function fetch() {
    loading.value = true
    error.value = null
    try {
      data.value = useMock ? mockIssues : await IssuesApi.list()
    } catch (e) {
      error.value = e
    } finally {
      loading.value = false
    }
  }

  if (import.meta.client) fetch()

  return { data, loading, error, refresh: fetch }
}
