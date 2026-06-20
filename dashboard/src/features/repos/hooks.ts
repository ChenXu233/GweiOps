'use client'

import useSWR from 'swr'
import type { Repo, Plugin, TeamSettings } from './types'
import { mockRepos, mockPlugins, mockTeamSettings } from '@/lib/mock'

const USE_MOCK = process.env.NEXT_PUBLIC_USE_MOCK === 'true'

const fetcher = (url: string) => fetch(url).then(r => r.json())

export function useRepos() {
  if (USE_MOCK) {
    return { data: mockRepos, isLoading: false, error: null }
  }
  return useSWR<Repo[]>('/api/repos', fetcher, { refreshInterval: 30_000 })
}

export function usePlugins() {
  if (USE_MOCK) {
    return { data: mockPlugins, isLoading: false, error: null }
  }
  return useSWR<Plugin[]>('/api/plugins', fetcher, { refreshInterval: 60_000 })
}

export function useTeamSettings() {
  if (USE_MOCK) {
    return { data: mockTeamSettings, isLoading: false, error: null }
  }
  return useSWR<TeamSettings>('/api/settings', fetcher)
}
