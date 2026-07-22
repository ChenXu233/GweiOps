import { ref, onUnmounted } from 'vue'
import { DashboardApi } from '../api/client'
import {
  mockDashboard,
  mockPendingIssues,
  mockOvernightEvents,
  mockCanaryStatuses,
} from '../mock'
import type { DashboardData, PendingIssue, OvernightEvent, CanaryStatus } from '../types/dashboard'

const USE_MOCK = import.meta.env.NUXT_PUBLIC_USE_MOCK === 'true'

export function useDashboard() {
  const data = ref<DashboardData | null>(null)
  const pendingIssues = ref<PendingIssue[]>([])
  const overnightEvents = ref<OvernightEvent[]>([])
  const canaryStatuses = ref<CanaryStatus[]>([])
  const loading = ref(true)
  const error = ref<unknown>(null)

  async function fetch() {
    loading.value = true
    error.value = null
    try {
      if (USE_MOCK) {
        data.value = mockDashboard
        pendingIssues.value = mockPendingIssues
        overnightEvents.value = mockOvernightEvents
        canaryStatuses.value = mockCanaryStatuses
      } else {
        const [d, p, o, c] = await Promise.all([
          DashboardApi.get(),
          DashboardApi.getPending(),
          DashboardApi.getOvernight(),
          DashboardApi.getCanary(),
        ])
        data.value = d
        pendingIssues.value = p
        overnightEvents.value = o
        canaryStatuses.value = c
      }
    } catch (e) {
      error.value = e
    } finally {
      loading.value = false
    }
  }

  if (import.meta.client) {
    fetch()
    const interval = setInterval(fetch, 10_000)
    onUnmounted(() => clearInterval(interval))
  }

  return { data, pendingIssues, overnightEvents, canaryStatuses, loading, error, refresh: fetch }
}
