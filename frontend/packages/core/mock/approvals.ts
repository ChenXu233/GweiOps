import { makeLedgerEffect } from './index'
import type { ApprovalItem, ApprovalOutcome } from '../types/approvals'

/**
 * 待放行队列的演示数据。
 * 都是"夜里被拦下的改变":不可逆的、被策略挡的、等一个人的观察窗口太短的。
 * id / 时间 / 绑定都照账本里的写法,免得两边对不上。
 */
export const mockApprovals: ApprovalItem[] = [
  {
    id: 'cu_01j9z5a3k8rn2v7',
    created_at: '2026-11-04T04:02:30+08:00',
    verdict: 'blocked',
    reason: '观察窗口 90 秒,短于人的反应时间,等人工放行',
    binding: 'github',
    tenant: 'default',
    handle: null,
    idempotency_key: 'wf-8831:effects:effect:0',
    facts: {},
    intent: { summary: '强制推送 main 分支以回退一次错误合并' },
    effect: makeLedgerEffect('repo.force_push', 'github.repo_ops'),
  },
  {
    id: 'cu_01j9z5b7w1qm4x9r',
    created_at: '2026-11-04T05:12:48+08:00',
    verdict: 'blocked',
    reason: '没有撤销任务也没有观察窗口,只能阻断',
    binding: 'postgres',
    tenant: 'default',
    handle: null,
    idempotency_key: 'wf-8855:effects:effect:0',
    facts: {},
    intent: { summary: '清理 audit_log 表中 90 天前的历史记录' },
    effect: makeLedgerEffect('db.purge', 'postgres.maintenance'),
  },
  {
    id: 'cu_01j9z5c9e3ty6p2k',
    created_at: '2026-11-04T06:08:19+08:00',
    verdict: 'blocked',
    reason: '策略要求生产环境变更必须带观察窗口',
    binding: 'github',
    tenant: 'default',
    handle: null,
    idempotency_key: 'wf-8860:effects:effect:0',
    facts: {},
    intent: { summary: '关闭仓库的必需状态检查以加速合并' },
    effect: makeLedgerEffect('repo.protection', 'github.repo_ops'),
  },
  {
    id: 'cu_01j9z5d2u5gh8n4m',
    created_at: '2026-11-04T06:41:55+08:00',
    verdict: 'blocked',
    reason: '写配置没有回滚能力,先等一个人看过',
    binding: 'gateway',
    tenant: 'default',
    handle: null,
    idempotency_key: 'wf-8864:effects:effect:0',
    facts: {},
    intent: { summary: '把网关限流阈值从 100 提到 500' },
    effect: makeLedgerEffect('config.write', 'gateway.config'),
  },
  {
    id: 'cu_01j9z5e6j7ds1z5n',
    created_at: '2026-11-04T07:03:12+08:00',
    verdict: 'blocked',
    reason: '生产密钥轮换要走双人复核,策略不认自动放行',
    binding: 'postgres',
    tenant: 'default',
    handle: null,
    idempotency_key: 'wf-8871:effects:effect:0',
    facts: {},
    intent: { summary: '轮换生产数据库的访问密钥' },
    effect: makeLedgerEffect('secret.rotate', 'postgres.maintenance'),
  },
]

/**
 * mock 里刻意留一次执行失败:密钥轮换没有可用提供者,放行之后引擎执行不出来,回 502。
 * 用来验证"失败原因要显示出来"这条路径真的接上了,不是只在纸面上。
 * 错误消息的形状跟 apiClient 抛的一样,走的是同一条解析路径。
 */
const FAILING_ON_APPROVE = 'cu_01j9z5e6j7ds1z5n'

/** 放行之后引擎把这条记成什么结论:没有回滚能力的,如实记成 irreversible。 */
const approveVerdicts = new Map<string, 'kept' | 'irreversible'>([
  ['cu_01j9z5a3k8rn2v7', 'kept'],
  ['cu_01j9z5b7w1qm4x9r', 'irreversible'],
  ['cu_01j9z5c9e3ty6p2k', 'kept'],
  ['cu_01j9z5d2u5gh8n4m', 'irreversible'],
])

function outcome(
  row: ApprovalItem,
  verdict: ApprovalItem['verdict'],
  reason: string,
): ApprovalOutcome {
  const latest: ApprovalItem = { ...row, verdict, reason }
  return { latest, history: [row, latest] }
}

export async function mockApprove(id: string): Promise<ApprovalOutcome> {
  const row = mockApprovals.find((r) => r.id === id)
  if (!row) throw new Error('API error: 404 Not Found')
  if (id === FAILING_ON_APPROVE) throw new Error('API error: 502 Internal Server Error')
  return outcome(row, approveVerdicts.get(id) ?? 'kept', '人工放行,执行后照常读窗口、照常验证')
}

export async function mockVeto(id: string): Promise<ApprovalOutcome> {
  const row = mockApprovals.find((r) => r.id === id)
  if (!row) throw new Error('API error: 404 Not Found')
  return outcome(row, 'vetoed', '人工否决,不做这次变更')
}