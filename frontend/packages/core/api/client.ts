// packages/core/api/client.ts
//
// 接口调用点。路径与响应体类型全部来自 ../../../contracts/openapi.json,
// 新增端点只要引擎声明了 response_model,这里就不用再手写一遍类型。
import { api } from './typed'
import type {
  CanaryStatus,
  DashboardData,
  OvernightEvent,
  PendingIssue,
} from '../types/dashboard'
import type { Issue } from '../types/issues'
import type { Plugin, Repo, TeamSettings } from '../types/repos'
import type { PluginManifestDTO, PluginWidgetDTO } from '../types/plugin'
import type { ChangeDetail, ChangeList } from '../types/changes'

export const DashboardApi = {
  get: () => api.get('/api/dashboard'),
  getPending: () => api.get('/api/dashboard/pending'),
  getOvernight: () => api.get('/api/dashboard/overnight'),
  getCanary: () => api.get('/api/dashboard/canary'),
}

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
  list: () => api.get('/api/issues'),
  get: (id: string) => api.get('/api/issues/{issue_id}', { path: { issue_id: id } }),
}

export const ReposApi = {
  list: () => api.get('/api/repos'),
}

export const PluginsApi = {
  list: () => api.get('/api/plugins'),
  // engine 原始清单(含 capabilities/widgets/pages 声明)
  manifests: () => api.get('/api/plugins'),
  widgets: (slot: string) => api.get('/api/plugins/widgets', { query: { slot } }),
}

export const MetricsApi = {
  list: (prefix?: string) => api.get('/api/metrics', { query: { prefix } }),
}

export const SettingsApi = {
  get: () => api.get('/api/settings'),
}

export const HealthApi = {
  get: () => api.get('/api/health'),
}

// 类型再导出:调用方需要注解时不必自己去找 schema
export type {
  CanaryStatus,
  ChangeDetail,
  ChangeList,
  DashboardData,
  Issue,
  OvernightEvent,
  PendingIssue,
  Plugin,
  PluginManifestDTO,
  PluginWidgetDTO,
  Repo,
  TeamSettings,
}
