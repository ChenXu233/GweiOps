'use client'

import useSWR from 'swr'
import type { Issue } from './types'
import { mockIssues } from '@/lib/mock'

const USE_MOCK = process.env.NEXT_PUBLIC_USE_MOCK === 'true'

const fetcher = (url: string) => fetch(url).then(r => r.json())

export function useIssues() {
  if (USE_MOCK) {
    return { data: mockIssues, isLoading: false, error: null }
  }
  return useSWR<Issue[]>('/api/issues', fetcher, { refreshInterval: 10_000 })
}

export function useIssue(id: string) {
  if (USE_MOCK) {
    const issue = mockIssues.find(i => i.id === id)
    return { data: issue ?? null, isLoading: false, error: issue ? null : 'Not found' }
  }
  return useSWR<Issue>(`/api/issues/${id}`, fetcher, { refreshInterval: 5_000 })
}
