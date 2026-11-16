// packages/core/types/repos.ts
import type { components } from '../api/schema'

type S = components['schemas']

export { type PluginWidget } from './plugin'

export type Repo = S['RepoDTO']
export type RepoStatus = Repo['status']
export type TeamSettings = S['SettingsDTO']

/**
 * 插件市场卡片:前端从清单 DTO 算出来的展示模型。`enabled` 来自引擎,
 * author / price 是展示用占位(引擎没有市场与计价概念)。
 */
export interface Plugin {
  id: string
  name: string
  description: string
  author: 'official' | 'community'
  price: number | null
  enabled: boolean
  reason: string
  error: string
  instances: string[]
  version: string
  type: string
  capabilities: string[]
  /** 插件声明了 iframe 页面时的页面标题(用于"打开页面"入口) */
  pageTitle?: string
}
