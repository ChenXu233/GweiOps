import { ref } from 'vue'
import { SettingsApi } from '../api/client'
import { mockTeamSettings } from '../mock'
import type { TeamSettings } from '../types/repos'

export function useSettings() {
  const useMock = useRuntimeConfig().public.useMock === true
  const data = ref<TeamSettings | null>(null)
  const loading = ref(true)
  const error = ref<unknown>(null)

  async function fetch() {
    loading.value = true
    error.value = null
    try {
      data.value = useMock ? mockTeamSettings : await SettingsApi.get()
    } catch (e) {
      error.value = e
    } finally {
      loading.value = false
    }
  }

  if (import.meta.client) fetch()

  return { data, loading, error, refresh: fetch }
}
