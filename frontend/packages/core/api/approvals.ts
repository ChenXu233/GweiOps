import { api } from './typed'
import type { ApprovalAction, ApprovalList, ApprovalOutcome } from '../types/approvals'

/**
 * 待放行队列的接口封装。
 * 引擎只把 blocked 这一种结论留在队列里,所以队列就是 /changes?verdict=blocked。
 */
export const ApprovalsApi = {
  list(limit = 100): Promise<ApprovalList> {
    return api.get('/api/changes', { query: { verdict: 'blocked', limit } })
  },
  approve(id: string): Promise<ApprovalOutcome> {
    return api.post('/api/changes/{unit_id}/approve', { path: { unit_id: id } })
  },
  veto(id: string): Promise<ApprovalOutcome> {
    return api.post('/api/changes/{unit_id}/veto', { path: { unit_id: id } })
  },
}

/**
 * 从错误里把状态码抠出来。
 * typed client 只抛 `API error: 502 Internal Server Error`,不带响应体,
 * 所以状态码是我们唯一能拿到的引擎信号。
 */
export function statusOf(err: unknown): number | undefined {
  const message = err instanceof Error ? err.message : ''
  const matched = message.match(/API error:\s*(\d{3})/)
  return matched ? Number(matched[1]) : undefined
}

/**
 * 引擎的错误语义 → 一句能直接给人看的话。
 * 逐条对着 engine/api/routes/changes.py 里的状态码写,不猜语义。
 */
export function describeFailure(action: ApprovalAction, status?: number): string {
  if (status === 502) {
    return action === 'approve'
      ? '引擎执行失败:放行之后这条变更没能执行完,它在账本里仍然是阻断状态。'
      : '引擎返回 502,这次否决没有写进账本。'
  }
  if (status === 503) return '绑定的能力当前没有可用提供者,引擎没能执行这条变更。'
  if (status === 409) {
    return action === 'approve'
      ? '这条变更的状态已经变了(可能已被放行或否决),刷新后再看。'
      : '这条变更已经执行过,只能撤销,不能否决。'
  }
  if (status === 404) return '账本里找不到这条变更,可能已经被清理。'
  if (status) return `引擎返回 ${status},这次操作没有生效。`
  return '这次操作没有生效,网络或引擎都没有给出原因。'
}
