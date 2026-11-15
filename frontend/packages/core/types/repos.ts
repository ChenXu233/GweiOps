// packages/core/types/repos.ts
import type { components } from '../api/schema'

type S = components['schemas']

export { type PluginWidget } from './plugin'

export type Repo = S['RepoDTO']
export type RepoStatus = Repo['status']
export type TeamSettings = S['SettingsDTO']

/**
 * 插件市场卡片。
 *
 * 这不是接口形状,而是前端从清单算出来的展示模型。`enabled` 来自引擎:
 * 它说这个插件此刻在不在流程里。**不要在前端猜**——写死 true 会让
 * 页面顶上的"X / N 已启用"永远是 N/N,那个数字就不再是信息。
 *
 * author / price 是展示用的占位:引擎没有市场概念,也没有计价。
 */
export interface Plugin {
  id: string
  name: string
  description: string
  author: 'official' | 'community'
  price: number | null
  /** 此刻能不能被解析到。false = 发现到了但没启用(或被停用)。 */
  enabled: boolean
  /** 引擎给出的状态说明:为什么是现在这个状态 */
  reason: string
  /** 活着的实例键。同一清单按租户/目标挂多实例时会有多个。 */
  instances: string[]
  version: string
  type: string
  capabilities: string[]
  /** 插件声明了 iframe 页面时的页面标题(用于"打开页面"入口) */
  pageTitle?: string
}
