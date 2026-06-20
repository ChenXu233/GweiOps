export type RepoStatus = 'running' | 'configuring' | 'paused'

export interface Repo {
  id: string
  name: string
  icon: string
  status: RepoStatus
  issueCount: number
  activeAgents: number
  lastSyncAt: string
}

export interface Plugin {
  id: string
  name: string
  icon: string
  description: string
  author: 'official' | 'community'
  price: number | null
  installed: boolean
}

export interface TeamSettings {
  teamName: string
  memberCount: number
  adminCount: number
  plan: string
  planPrice: string
  issueQuota: string
  notificationChannels: string[]
  ssoProvider: string
}
