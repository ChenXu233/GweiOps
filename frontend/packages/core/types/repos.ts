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
  /** 插件声明了 iframe 页面时的页面标题(用于"打开页面"入口) */
  pageTitle?: string
}

export type PluginWidgetVariant = 'default' | 'green' | 'yellow' | 'red'

export interface PluginWidgetMetric {
  label: string
  value: string | number
  sub?: string
  variant?: PluginWidgetVariant
}

export interface PluginWidgetItem {
  text: string
}

/** 插件经 manifest 声明的 UI 卡片(声明式 schema,核心渲染) */
export interface PluginWidget {
  plugin: string
  slot: string
  kind: 'metric' | 'list'
  span: number
  title: string
  metrics?: PluginWidgetMetric[]
  items?: PluginWidgetItem[]
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
