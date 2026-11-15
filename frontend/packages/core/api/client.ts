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
  // 运行期启停:不用重启进程。决定写进库里,下次启动按它来。
  enable: (name: string) =>
    api.post('/api/plugins/{name}/enable', { path: { name } }),
  disable: (name: string) =>
    api.post('/api/plugins/{name}/disable', { path: { name } }),
  // 重扫插件目录:新出现的按决定启用,已经删掉的停用
  rescan: () => api.post('/api/plugins/rescan'),
}

export const MetricsApi = {
  list: (prefix?: string) => api.get('/api/metrics', { query: { prefix } }),
}

export const SettingsApi = {
  get: () => api.get('/api/settings'),
}

// 插件/接入层声明的配置项——回显规则由每个字段自己声明,前端不猜。
export const SettingsScopesApi = {
  list: () => api.get('/api/settings/scopes'),
  put: (scope: string, values: Record<string, string>) =>
    api.put('/api/settings/scopes/{scope_name}', {
      path: { scope_name: scope },
      body: { values },
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