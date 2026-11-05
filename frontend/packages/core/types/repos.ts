// packages/core/types/repos.ts
import type { components } from '../api/schema'

type S = components['schemas']

export { type PluginWidget } from './plugin'

export type Repo = S['RepoDTO']
export type RepoStatus = Repo['status']
export type TeamSettings = S['SettingsDTO']

/**
 * 插件市场卡片。
 * 这不是接口形状,而是前端从清单算出来的展示模型:
 * author / price / installed 都是本地判断或占位,引擎不返回。
 */
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
