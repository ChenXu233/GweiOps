import type { DashboardData, PendingIssue, OvernightEvent, CanaryStatus } from '../types/dashboard'
import type { Issue } from '../types/issues'
import type { Repo, Plugin, TeamSettings } from '../types/repos'

const BASE_URL = import.meta.env.NUXT_PUBLIC_API_BASE || '/api'

export const apiClient = {
  async get<T>(url: string): Promise<T> {
    const res = await fetch(`${BASE_URL}${url}`)
    if (!res.ok) throw new Error(`API error: ${res.status} ${res.statusText}`)
    return res.json()
  },
  async post<T>(url: string, body?: unknown): Promise<T> {
    const res = await fetch(`${BASE_URL}${url}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined,
    })
    if (!res.ok) throw new Error(`API error: ${res.status} ${res.statusText}`)
    return res.json()
  },
  async put<T>(url: string, body: unknown): Promise<T> {
    const res = await fetch(`${BASE_URL}${url}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!res.ok) throw new Error(`API error: ${res.status} ${res.statusText}`)
    return res.json()
  },
}

// Placeholder API endpoints — will be replaced by orval-generated code
export const DashboardApi = {
  get: () => apiClient.get<DashboardData>('/dashboard'),
  getPending: () => apiClient.get<PendingIssue[]>('/dashboard/pending'),
  getOvernight: () => apiClient.get<OvernightEvent[]>('/dashboard/overnight'),
  getCanary: () => apiClient.get<CanaryStatus[]>('/dashboard/canary'),
}

export const IssuesApi = {
  list: () => apiClient.get<Issue[]>('/issues'),
  get: (id: string) => apiClient.get<Issue>(`/issues/${encodeURIComponent(id)}`),
}

export const ReposApi = {
  list: () => apiClient.get<Repo[]>('/repos'),
}

export const PluginsApi = {
  list: () => apiClient.get<Plugin[]>('/plugins'),
}

export const SettingsApi = {
  get: () => apiClient.get<TeamSettings>('/settings'),
}
