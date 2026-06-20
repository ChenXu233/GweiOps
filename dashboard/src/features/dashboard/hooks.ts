'use client'

import useSWR from 'swr'
import type { DashboardData, PendingIssue, OvernightEvent, CanaryStatus } from './types'
import { mockDashboard, mockPendingIssues, mockOvernightEvents, mockCanaryStatuses } from '@/lib/mock'

const USE_MOCK = process.env.NEXT_PUBLIC_USE_MOCK === 'true'

const fetcher = (url: string) => fetch(url).then(r => r.json())

export function useDashboardData() {
  if (USE_MOCK) {
    return { data: mockDashboard, isLoading: false, error: null }
  }
  return useSWR<DashboardData>('/api/dashboard', fetcher, { refreshInterval: 10_000 })
}

export function usePendingIssues() {
  if (USE_MOCK) {
    return { data: mockPendingIssues, isLoading: false, error: null }
  }
  return useSWR<PendingIssue[]>('/api/dashboard/pending', fetcher, { refreshInterval: 10_000 })
}

export function useOvernightEvents() {
  if (USE_MOCK) {
    return { data: mockOvernightEvents, isLoading: false, error: null }
  }
  return useSWR<OvernightEvent[]>('/api/dashboard/overnight', fetcher, { refreshInterval: 30_000 })
}

export function useCanaryStatuses() {
  if (USE_MOCK) {
    return { data: mockCanaryStatuses, isLoading: false, error: null }
  }
  return useSWR<CanaryStatus[]>('/api/dashboard/canary', fetcher, { refreshInterval: 5_000 })
}
