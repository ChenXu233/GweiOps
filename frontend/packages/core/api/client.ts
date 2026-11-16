// packages/core/api/client.ts
//
// 接口调用点。路径与响应体类型全部来自 ../../../contracts/openapi.json,
// 新增端点只要引擎声明了 response_model,这里就不用再手写一遍类型。
import { api } from './typed'
import type { IssueBoard, IssueTimeline } from '../types/issues'
import type { Plugin, Repo, TeamSettings } from '../types/repos'
import type { PluginManifestDTO, PluginWidgetDTO } from '../types/plugin'
import type { ChangeDetail, ChangeList } from '../types/changes'

export const ChangesApi = {
  list: (params?: { verdict?: string; binding?: string; limit?: number }) =>
    api.get('/api/changes', { query: params }),
  get: (id: string) => api.get('/api/changes/{unit_id}', { path: { unit_id: id } }),
  rollback: (id: string, reason?: string) =>
    api.post('/api/changes/{unit_id}/rollback', { path: { unit_id: id }, query: { reason } }),
  approve: (id: string, reason?: string) =>
    api.post('/api/changes/{unit_id}/approve', { path: { unit_id: id }, query: { reason } }),
  veto: (id: string, reason?: string) =>
    api.post('/api/changes/{unit_id}/veto', { path: { unit_id: id }, query: { reason } }),
}

export const IssuesApi = {
  // 一个议题的全部证据。三个状态与分段都由后端给,前端不拼。
  timeline: (id: string) =>
    api.get('/api/issues/{issue_id}/timeline', { path: { issue_id: id } }),
  // 首页那张板:三段、三个数。空在第一个议题之前也是一次安排,不是错误。
  board: (limit?: number) => api.get('/api/board', { query: { limit } }),
  // 接着这条线再改一轮:话题与分支不变,PR 不会新开。
  continueRound: (id: string, instruction: string) =>
    api.post('/api/issues/{issue_id}/continue', {
      path: { issue_id: id },
      body: { instruction },
    }),
}

export const ReposApi = {
  list: () => api.get('/api/repos'),
}

export const PluginsApi = {
  list: () => api.get('/api/plugins'),
  // engine 原始清单(含 capabilities/widgets/pages 声明、enabled 状态)
  manifests: () => api.get('/api/plugins'),
  widgets: (slot: string) => api.get('/api/plugins/widgets', { query: { slot } }),
  enable: (name: string) =>
    api.post('/api/plugins/{name}/enable', { path: { name } }),
  disable: (name: string) =>
    api.post('/api/plugins/{name}/disable', { path: { name } }),
  rescan: () => api.post('/api/plugins/rescan'),
}

export const MetricsApi = {
  list: (prefix?: string) => api.get('/api/metrics', { query: { prefix } }),
}

export const SettingsApi = {
  get: () => api.get('/api/settings'),
}

// 插件/接入层声明的配置项——回显规则由每个字段自己声明,前端不猜。
// put 的响应里带 push_error:值已经存下了,只是没推到插件那边。两件事要分开说。
export const SettingsScopesApi = {
  list: () => api.get('/api/settings/scopes'),
  put: (scope: string, values: Record<string, string>) =>
    api.put('/api/settings/scopes/{scope_name}', {
      path: { scope_name: scope },
      body: { values },
    }),
}

// MCP 接入用的密钥。明文只在签发那一次的响应里,列表永远只有 hint。
// resources / tools 两份清单来自引擎:签密钥时挑的就是它们,前端不自己编。
export const ApiKeysApi = {
  list: () => api.get('/api/keys'),
  issue: (body: {
    name: string
    permissions: string[]
    tools?: string[]
    bindings?: string[]
    expires_at?: string
  }) => api.post('/api/keys', { body }),
  revoke: (id: string) => api.delete('/api/keys/{key_id}', { path: { key_id: id } }),
  resources: () => api.get('/api/keys/resources'),
  tools: () => api.get('/api/keys/tools'),
}

// 发布配置:租户默认(key=*)与仓库行(key=owner/repo),value 是一份 JSON 声明。
// 生效值(effective)由引擎按四层合并算好,页面只展示、不自己拼。
export const ReleaseSettingsApi = {
  get: () => api.get('/api/settings/release'),
  putTenantDefault: (values: Record<string, string>) =>
    api.put('/api/settings/release/tenant-default', { body: { values } }),
  putRepo: (repo: string, values: Record<string, string>) =>
    api.put('/api/settings/release/repos/{repo_full_name}', {
      path: { repo_full_name: repo },
      body: { values },
    }),
  deleteTenantDefault: () => api.delete('/api/settings/release/tenant-default'),
  deleteRepo: (repo: string) =>
    api.delete('/api/settings/release/repos/{repo_full_name}', {
      path: { repo_full_name: repo },
    }),
}

export const HealthApi = {
  get: () => api.get('/api/health'),
}

// 类型再导出:调用方需要注解时不必自己去找 schema
export type {
  ChangeDetail,
  ChangeList,
  IssueBoard,
  IssueTimeline,
  Plugin,
  PluginManifestDTO,
  PluginWidgetDTO,
  Repo,
  TeamSettings,
}