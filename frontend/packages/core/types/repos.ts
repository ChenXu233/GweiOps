export type { PluginWidget } from './plugin'

export type RepoStatus = 'running' | 'configuring' | 'paused'

export interface Repo {
  id: string
  name: string
  status: RepoStatus
  issueCount: number
  activeAgents: number
  lastSyncAt: string
}

export interface Plugin {
  id: string
  name: string
  description: string
  author: 'official' | 'community'
  price: number | null
  installed: boolean
  /** 插件声明了 iframe 页面时的页面标题(用于"打开页面"入口) */
  pageTitle?: string
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
