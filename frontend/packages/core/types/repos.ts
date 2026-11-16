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

// 工作区:租户在控制台的名字。repo / source 只是列表上要说清的两件事。
export type Workspace = S['WorkspaceDTO']
export type WorkspaceList = S['WorkspaceListDTO']

/**
 * 项目:仓库上面那一级,也是范围闸的中间档。
 *
 * 它是资源不只是标签——项目级的可见性、默认动作、凭据都摆在这里。`repos` /
 * `issues` 是它下面那些仓库的数,用来在选择器里说清"这一档有多大"。
 */
export type Project = S['ProjectDTO']

/** 范围闸的三档:整个工作区 → 某个项目 → 某个仓库。 */
export interface ScopePicker {
  project: string
  repo: string
}
