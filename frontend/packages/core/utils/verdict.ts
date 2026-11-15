// packages/core/utils/verdict.ts
//
// 议题相关的界面用同一套说法:三个状态、七种结论、等你做什么。
// 账本页有自己的一套话术(它要"原词感"),所以这里服务的是议题侧,不是全站唯一。
import type { IssueState } from '../types/issues'

/** 列表与详情共用的三个状态。 */
export const stateMeta: Record<IssueState, { label: string; cls: string }> = {
  waiting: { label: '等我', cls: 'chip-warn' },
  running: { label: '在跑', cls: 'chip-info' },
  landed: { label: '落了', cls: 'chip-ok' },
}

const VERDICT_LABEL: Record<string, string> = {
  kept: '已改好',
  blocked: '等你放行',
  unknown: '要去下游核',
  irreversible: '撤不回来了',
  failed: '没生效',
  rolled_back: '已撤回',
  vetoed: '没让它做',
  pending: '在执行',
}

/** 一个结论本身叫什么。原词不出现在议题界面上。 */
export function verdictLabel(verdict: string): string {
  return VERDICT_LABEL[verdict] ?? (verdict || '—')
}

function clock(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const p = (n: number) => String(n).padStart(2, '0')
  return p(d.getHours()) + ':' + p(d.getMinutes())
}

/**
 * 结论 + 还撤不撤得回来。这两件事分开算:kept 也可能已经过了撤销窗口。
 */
export function outcomeChip(
  verdict: string,
  undoable = false,
  expiresAt = '',
): { label: string; cls: string } {
  if (verdict === 'kept') {
    if (!undoable) return { label: '已改好 · 撤不回来', cls: '' }
    const at = clock(expiresAt)
    return { label: at ? '还能撤到 ' + at : '还能撤', cls: 'chip-lime' }
  }
  const cls =
    verdict === 'blocked' || verdict === 'unknown'
      ? 'chip-warn'
      : verdict === 'irreversible'
        ? 'chip-bad'
        : verdict === 'pending'
          ? 'chip-info'
          : ''
  return { label: verdictLabel(verdict), cls }
}

/** 列表上"等你做什么"。没有动作就返回空串——页面据此不渲染那一句。 */
export function actionLabel(action: string): string {
  if (action === 'approve') return '等你放行'
  if (action === 'investigate') return '去下游核'
  return ''
}

/** 多久以前。列表上的"停留了多久"用它;解析不了就原样给回来。 */
export function since(iso: string, now = Date.now()): string {
  if (!iso) return ''
  const at = new Date(iso).getTime()
  if (Number.isNaN(at)) return iso
  const seconds = Math.max(0, Math.round((now - at) / 1000))
  if (seconds < 60) return '刚刚'
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return minutes + ' 分钟前'
  const hours = Math.round(minutes / 60)
  if (hours < 24) return hours + ' 小时前'
  return Math.round(hours / 24) + ' 天前'
}
