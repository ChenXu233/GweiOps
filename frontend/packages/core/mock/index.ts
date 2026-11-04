import type { DashboardData, PendingIssue, OvernightEvent, CanaryStatus } from '../types/dashboard'
import type { Issue } from '../types/issues'
import type { Repo, Plugin, TeamSettings } from '../types/repos'
import type { PluginWidget } from '../types/plugin'
import type { ChangeRow } from '../types/changes'

export const mockDashboard: DashboardData = {
  status: 'healthy',
  consecutiveDays: 14,
  lastIncident: '2026-06-07',
  pendingReview: 3,
  overnightFixed: 7,
  memoryEntries: 1284,
  mttr: 8.2,
  successRate: 98.5,
  activeAgents: 5,
  healthHistory: [true, true, true, true, true, true, false, true, true, true],
}

export const mockPendingIssues: PendingIssue[] = [
  { id: '#42', title: '内存泄漏 — 生产环境 Pod 内存持续增长', severity: 'critical', patchCount: 3, status: 'canary' },
  { id: 'CVE-2026-1234', title: '依赖漏洞 — lodash 原型污染', severity: 'medium', patchCount: 2, status: 'pending_review' },
  { id: '#89', title: '文档缺失 — API 认证说明不完整', severity: 'low', patchCount: 1, status: 'pending_review' },
]

export const mockOvernightEvents: OvernightEvent[] = [
  { time: '03:17', title: '内存泄漏自动修复', description: '诊断 → 3 方案生成 → 金丝雀 1%→10%→50%→100% → 完成', result: 'success' },
  { time: '04:30', title: 'CVE 应急补丁', description: '上游无修复 → 生成 patch-package → 金丝雀完成 → 上游追踪启动', result: 'success' },
  { time: '05:12', title: '流量过载自动扩容', description: 'QPS 超限 → 扩容 3→10 Pod → 错误率 15%→0.2% → 恢复', result: 'success' },
]

export const mockCanaryStatuses: CanaryStatus[] = [
  {
    issueId: '#42',
    issueTitle: '内存泄漏',
    currentStep: '50%',
    steps: ['1%', '10%', '50%', '100%'],
    metrics: { passRate: 98.7, errorRate: 0.2, p99Latency: '42ms', memoryPeak: '512MB' },
  },
]

export const mockIssues: Issue[] = [
  {
    id: '#42',
    title: '内存泄漏 — 生产环境 Pod 内存持续增长',
    source: 'prometheus',
    severity: 'critical',
    status: 'canary',
    repo: 'acme/api-gateway',
    triggeredAt: '2026-06-21 03:17',
    patches: [
      { id: 'a', type: 'hotfix', risk: 'low', lines: 3, passRate: 99.2, latency: '+0.1ms', description: '添加资源释放逻辑，最小改动。适用于紧急止血，不解决根因。' },
      { id: 'b', type: 'proper', risk: 'medium', lines: 28, passRate: 98.7, latency: '+0.3ms', description: '重构连接池管理，引入引用计数机制。从根本上解决资源泄漏问题。', selected: true },
      { id: 'c', type: 'refactor', risk: 'high', lines: 156, passRate: 97.1, latency: '-0.5ms', description: '替换为对象池模式，全面重构连接生命周期管理。长期最优但改动大。' },
    ],
    canary: {
      current: '50%',
      steps: ['1%', '10%', '50%', '100%'],
      completedSteps: ['1%', '10%'],
      metrics: { passRate: 98.7, errorRate: 0.2, p99Latency: '42ms', memoryPeak: '512MB' },
    },
    timeline: [
      { id: 'sense', label: '感知', status: 'done' },
      { id: 'diagnose', label: '诊断', status: 'done' },
      { id: 'generate', label: '方案生成', status: 'done' },
      { id: 'ci', label: 'CI 构建', status: 'done' },
      { id: 'canary', label: '金丝雀验证', status: 'active' },
      { id: 'expand', label: '扩流', status: 'pending' },
      { id: 'review', label: '终审', status: 'pending' },
    ],
  },
  {
    id: 'CVE-2026-1234',
    title: '依赖漏洞 — lodash 原型污染',
    source: 'trivy',
    severity: 'medium',
    status: 'pending_review',
    repo: 'acme/api-gateway',
    triggeredAt: '2026-06-21 04:30',
    patches: [
      { id: 'a', type: 'upstream', risk: 'low', lines: 1, passRate: 99.8, latency: '0ms', description: '上游已发布修复版本 v4.17.21，直接升级依赖版本。' },
      { id: 'b', type: 'patch', risk: 'low', lines: 5, passRate: 99.5, latency: '+0.05ms', description: '生成 patch-package 应急补丁，同时启动上游追踪。' },
    ],
    timeline: [
      { id: 'sense', label: '感知', status: 'done' },
      { id: 'diagnose', label: '诊断', status: 'done' },
      { id: 'generate', label: '方案生成', status: 'done' },
      { id: 'ci', label: 'CI 构建', status: 'pending' },
      { id: 'canary', label: '金丝雀验证', status: 'pending' },
      { id: 'expand', label: '扩流', status: 'pending' },
      { id: 'review', label: '终审', status: 'pending' },
    ],
  },
  {
    id: '#89',
    title: '文档缺失 — API 认证说明不完整',
    source: 'github_issue',
    severity: 'low',
    status: 'pending_review',
    repo: 'acme/auth-service',
    triggeredAt: '2026-06-21 06:00',
    patches: [
      { id: 'a', type: 'docs', risk: 'low', lines: 42, passRate: 100, latency: '0ms', description: '补充 API 认证文档，包含 OAuth2 流程说明和示例代码。' },
    ],
    timeline: [
      { id: 'sense', label: '感知', status: 'done' },
      { id: 'diagnose', label: '诊断', status: 'done' },
      { id: 'generate', label: '方案生成', status: 'done' },
      { id: 'ci', label: 'CI 构建', status: 'pending' },
      { id: 'canary', label: '金丝雀验证', status: 'pending' },
      { id: 'expand', label: '扩流', status: 'pending' },
      { id: 'review', label: '终审', status: 'pending' },
    ],
  },
]

export const mockRepos: Repo[] = [
  { id: '1', name: 'acme/api-gateway', status: 'running', issueCount: 12, activeAgents: 3, lastSyncAt: '2 分钟前' },
  { id: '2', name: 'acme/auth-service', status: 'running', issueCount: 5, activeAgents: 1, lastSyncAt: '5 分钟前' },
  { id: '3', name: 'acme/frontend', status: 'configuring', issueCount: 0, activeAgents: 0, lastSyncAt: '—' },
]

export const mockPlugins: Plugin[] = [
  { id: 'upstream-tracker', name: '上游追踪', description: '自动监控依赖仓库 Releases，检测 CVE 修复版本，生成切换 PR。', author: 'official', price: null, installed: true },
  { id: 'canary', name: '金丝雀发布', description: '标准金丝雀流程 1%→10%→50%→100%，自动回滚触发。', author: 'official', price: null, installed: true },
  { id: 'k8s-scaler', name: 'K8s 扩容', description: '检测流量过载，自动调用 K8s API 水平扩容 Pod 副本数。', author: 'official', price: null, installed: false },
  { id: 'security-compliance', name: '安全合规', description: '审计日志、双人审批、禁止未经审计的补丁。金融行业专用。', author: 'official', price: 29, installed: false },
  { id: 'feishu-notify', name: '飞书通知', description: '修复报告、审核提醒、异常告警推送至飞书群。', author: 'community', price: null, installed: true },
  { id: 'ai-inference', name: 'AI 推理运维', description: 'GPU 扩缩容、模型版本回滚、推理延迟监控。', author: 'official', price: 49, installed: false },
]

export const mockTeamSettings: TeamSettings = {
  teamName: 'Acme Corp',
  memberCount: 5,
  adminCount: 2,
  plan: '专业版',
  planPrice: '$149/月',
  issueQuota: '500 Issues/月',
  notificationChannels: ['飞书', '邮件'],
  ssoProvider: 'GitHub OAuth',
}

export const mockPluginWidgets: PluginWidget[] = [
  {
    plugin: 'observer-agent',
    slot: 'dashboard.bento',
    kind: 'metric',
    span: 1,
    title: '观测采样',
    metrics: [{ label: '采样间隔', value: '60s', sub: '周期触发(静态演示)', variant: 'green' }],
  },
]

export const mockChanges: ChangeRow[] = [
  {
    id: 'cu_01j9z3k4m7qf2n8v',
    created_at: '2026-11-04T03:17:00+08:00',
    verdict: 'kept',
    reason: '金丝雀 1%→10%→50%→100% 全量通过,自动保留',
    binding: 'github',
    tenant: 'default',
    handle: 'ghc_8812',
    idempotency_key: 'wf-8812:effects:effect:0',
    intent: { summary: '在 api-gateway#42 上发布内存泄漏修复的验证评论' },
    effect: { capability: 'comment.create', task: 'github.comment_bridge' },
  },
  {
    id: 'cu_01j9z3p8r2vk5m1c',
    created_at: '2026-11-04T03:44:12+08:00',
    verdict: 'kept',
    reason: '错误率回落到 0.2%,副本数保留在 10',
    binding: 'compose',
    tenant: 'default',
    handle: 'cmp_api_1',
    idempotency_key: 'wf-8820:effects:effect:0',
    intent: { summary: '把 api 服务从 3 副本扩到 10 副本以吸收流量峰值' },
    effect: { capability: 'compose.scale', task: 'docker-compose.scale' },
  },
  {
    id: 'cu_01j9z3t6x8bn4p7q',
    created_at: '2026-11-04T04:02:30+08:00',
    verdict: 'blocked',
    reason: '观察窗口 90 秒,短于人的反应时间,等人工放行',
    binding: 'github',
    tenant: 'default',
    handle: null,
    idempotency_key: 'wf-8831:effects:effect:0',
    intent: { summary: '强制推送 main 分支以回退一次错误合并' },
    effect: { capability: 'repo.force_push', task: 'github.repo_ops' },
  },
  {
    id: 'cu_01j9z3w1q5dm8s3t',
    created_at: '2026-11-04T04:31:05+08:00',
    verdict: 'rolled_back',
    reason: 'P99 从 42ms 升到 118ms,撤销扩容',
    binding: 'compose',
    tenant: 'default',
    handle: 'cmp_api_1',
    idempotency_key: 'wf-8840:effects:effect:0',
    intent: { summary: '把 worker 服务从 4 副本扩到 16 副本' },
    effect: { capability: 'compose.scale', task: 'docker-compose.scale' },
  },
  {
    id: 'cu_01j9z40h7k3vq9nb',
    created_at: '2026-11-04T05:12:48+08:00',
    verdict: 'irreversible',
    reason: '没有撤销任务也没有观察窗口,只能阻断',
    binding: 'postgres',
    tenant: 'default',
    handle: null,
    idempotency_key: 'wf-8855:effects:effect:0',
    intent: { summary: '清理 audit_log 表中 90 天前的历史记录' },
  effect: { capability: 'db.purge', task: 'postgres.maintenance' },
  },
  {
    id: 'cu_01j9z44m2p6r8w4x',
    created_at: '2026-11-04T06:08:19+08:00',
    verdict: 'vetoed',
    reason: '策略要求生产环境变更必须带观察窗口',
    binding: 'github',
    tenant: 'default',
    handle: null,
    idempotency_key: 'wf-8860:effects:effect:0',
    intent: { summary: '关闭仓库的必需状态检查以加速合并' },
    effect: { capability: 'repo.protection', task: 'github.repo_ops' },
  },
]

