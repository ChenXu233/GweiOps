// packages/core/types/dashboard.ts
// 形状全部来自 openapi.json(经 pnpm gen:api 生成),不再手抄字段。
import type { components } from '../api/schema'

type S = components['schemas']

/** 系统态势。引擎目前恒为 "healthy",类型如实是字符串,不假装有更细的枚举。 */
export type SystemStatus = S['DashboardDTO']['status']

export type DashboardData = S['DashboardDTO']
export type PendingIssue = S['PendingIssueDTO']
export type PendingIssueStatus = PendingIssue['status']
export type OvernightEvent = S['OvernightEventDTO']
export type CanaryMetrics = S['CanaryMetricsDTO']
export type CanaryStatus = S['CanaryStatusDTO']
