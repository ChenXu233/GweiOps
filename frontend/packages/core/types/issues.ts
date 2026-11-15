// packages/core/types/issues.ts
import type { components } from '../api/schema'

type S = components['schemas']

// --- 议题时间线 ---------------------------------------------------------
// 一个议题的全部证据:三个状态 + 各轮次的分段。字段与 IssueTimelineDTO 同源。
export type IssueTimeline = S['IssueTimelineDTO']
export type TimelineRound = S['TimelineRoundDTO']
export type TimelineSegment = S['TimelineSegmentDTO']
export type TimelineEvidence = S['TimelineEvidenceDTO']
export type TimelineBranch = S['TimelineBranchDTO']

/** 用户只看到这三个:等我 / 在跑 / 落了。七种结论的原词留在账本页。 */
export type IssueState = IssueTimeline['state']
/** 一段一件事。 */
export type SegmentKind = TimelineSegment['kind']

// --- 议题板 -------------------------------------------------------------
// 首页那张列表:一段一个状态的卡片。三个状态与详情页同一套判定。
export type IssueBoard = S['IssueBoardDTO']
export type IssueCard = S['IssueCardDTO']
/** 等你做什么:放行 / 去下游核 / 没有。 */
export type IssueAction = IssueCard['action']