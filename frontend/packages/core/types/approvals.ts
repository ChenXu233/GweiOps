// packages/core/types/approvals.ts
import type { ChangeDetail, ChangeRow } from './changes'
import type { Tone } from '../utils/tone'

/**
 * 待放行队列里的一条阻断记录。
 * 形状与账本一致:引擎写什么,这里就接什么,前端不改写。
 */
export type ApprovalItem = ChangeRow

/** GET /api/changes?verdict=blocked 的返回形状。 */
export type ApprovalList = {
  items: ApprovalItem[]
  total: number
}

/** POST /api/changes/{id}/approve|veto 的返回形状。 */
export type ApprovalOutcome = ChangeDetail

export type ApprovalAction = 'approve' | 'veto'

/**
 * 阻断原因的分类。
 * 引擎只给一段自由文本 reason,分类是前端对这段文本的读法,不是引擎给的字段。
 */
export type BlockReasonKind = 'irreversible' | 'policy' | 'window' | 'other'

export interface BlockReasonMeta {
  kind: BlockReasonKind
  label: string
  tone: Tone
}

/** 一次放行/否决失败之后,留给人看的一句话。 */
export interface ApprovalFailure {
  action: ApprovalAction
  id: string
  message: string
  status?: number
}

/** 操作成功后的回执。 */
export interface ApprovalNotice {
  tone: 'ok'
  text: string
}
