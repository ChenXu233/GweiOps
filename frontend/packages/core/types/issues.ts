// packages/core/types/issues.ts
import type { components } from '../api/schema'

type S = components['schemas']

export type Issue = S['IssueDTO']
export type Patch = S['PatchDTO']
export type TimelineStep = S['TimelineStepDTO']
export type CanaryProgress = S['CanaryProgressDTO']

export type IssueSeverity = Issue['severity']
export type IssueStatus = Issue['status']
export type IssueSource = Issue['source']

// 类型与风险是插件写进库的自由文本,引擎不做枚举约束,
// 所以这里也是 string;前端只用它查文案表,查不到就原样显示。
export type PatchType = Patch['type']
export type PatchRisk = Patch['risk']
