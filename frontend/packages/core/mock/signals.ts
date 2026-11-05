import type { PluginManifestDTO } from '../types/plugin'
import type { Repo } from '../types/repos'

/**
 * 信号源页面的 mock 数据。
 *
 * 插件清单照抄 plugins/builtin 下真实存在的 manifest,能力名与真实清单一致,
 * 便于对着引擎核对。
 *
 * 这里同时放了 github-adapter 与 github-app-adapter:前者默认 default_enabled: false,
 * 引擎不会加载;但把 PLUGINS_ENABLED 指向它(清单里就是这么写的)之后,
 * 两个适配器会在场,能力有重叠 —— 这正是"同一个能力出现在多个插件下"的样子。
 *
 * lastSyncAt 用 ISO,与 GET /api/repos 返回的形状一致。
 */

export const mockSignalRepos: Repo[] = [
  {
    id: '1',
    name: 'acme/api-gateway',
    icon: '📦',
    status: 'running',
    issueCount: 12,
    activeAgents: 3,
    lastSyncAt: '2026-11-04T13:41:00+08:00',
  },
  {
    id: '2',
    name: 'acme/auth-service',
    icon: '📦',
    status: 'running',
    issueCount: 5,
    activeAgents: 1,
    lastSyncAt: '2026-11-04T13:38:00+08:00',
  },
  {
    id: '3',
    name: 'acme/frontend',
    icon: '📦',
    status: 'configuring',
    issueCount: 0,
    activeAgents: 0,
    lastSyncAt: '2026-11-04T09:12:00+08:00',
  },
  {
    id: '4',
    name: 'acme/data-pipeline',
    icon: '📦',
    status: 'paused',
    issueCount: 3,
    activeAgents: 0,
    lastSyncAt: '2026-11-01T22:05:00+08:00',
  },
]

export const mockSignalPlugins: PluginManifestDTO[] = [
  {
    name: 'github-app-adapter',
    version: '1.0.0',
    type: 'adapter',
    description: 'GitHub App 适配器,通过 GitHub App 进行认证和交互',
    capabilities: [
      'issue.read',
      'issue.write',
      'comment.read',
      'comment.write',
      'label.write',
      'webhook.receive',
      'webhook.verify',
      'comment.create',
    ],
    widgets: [],
    pages: [],
  },
  {
    name: 'github-adapter',
    version: '1.0.0',
    type: 'adapter',
    description: 'GitHub 托管适配器(默认不加载,PLUGINS_ENABLED 指向它时才在)',
    capabilities: [
      'issue.read',
      'issue.write',
      'pr.read',
      'pr.write',
      'pr.merge',
      'comment.read',
      'comment.write',
      'webhook.receive',
    ],
    widgets: [],
    pages: [],
  },
  {
    name: 'sensor-agent',
    version: '2.0.0',
    type: 'agent',
    description: '感知智能体,使用 LLM 分析 Issue 内容并提供智能回复',
    capabilities: [
      'issue.label',
      'issue.completeness_check',
      'issue.duplicate_detection',
      'issue.llm_analysis',
    ],
    widgets: [],
    pages: [],
  },
  {
    name: 'fixer-agent',
    version: '1.0.0',
    type: 'agent',
    description: '修复智能体,生成修复补丁',
    capabilities: ['patch.generate', 'code.review'],
    widgets: [],
    pages: [],
  },
  {
    name: 'intent-builder',
    version: '0.1.0',
    type: 'agent',
    description: '把信号与已有分析组装成 intent(harness 切缝的参考实现)',
    capabilities: ['intent.propose'],
    widgets: [],
    pages: [],
  },
  {
    name: 'docker-compose',
    version: '0.1.0',
    type: 'action',
    description: '用 docker compose 执行可撤销的服务变更,是变更单元契约的第一个下游样例',
    capabilities: ['compose.scale'],
    widgets: [],
    pages: [],
  },
  {
    name: 'observer-agent',
    version: '1.0.0',
    type: 'agent',
    description: 'UI 扩展示例:声明式 widget + iframe 页面(不提供能力,不订阅事件)',
    capabilities: [],
    widgets: [],
    pages: [{ title: '观测采样', entry: 'index.html' }],
  },
]