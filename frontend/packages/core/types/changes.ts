// packages/core/types/changes.ts
import type { components } from '../api/schema'

type S = components['schemas']

/** 账本一行。字段由引擎的 ChangeRowDTO 决定,前端不额外加工。 */
export type ChangeRow = S['ChangeRowDTO']
export type ChangeVerdict = ChangeRow['verdict']
export type ChangeIntent = S['ChangeIntentDTO']
export type ChangeEffect = S['ChangeEffectDTO']

/** GET /api/changes 的返回体。 */
export type ChangeList = S['ChangeListDTO']

/** 单个单元的全部事件(执行、放行、否决、撤销各一行)。 */
export type ChangeDetail = S['ChangeDetailDTO']
