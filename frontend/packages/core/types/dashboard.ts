import type { IssueSeverity } from './issues'

export type SystemStatus = 'healthy' | 'warning' | 'critical'
export type PendingIssueStatus = 'pending_review' | 'canary' | 'approved' | 'completed' | 'rolled_back'

export interface CanaryMetrics {
  passRate: number
  errorRate: number
  p99Latency: string
  memoryPeak: string
}

export interface DashboardData {
  status: SystemStatus
  consecutiveDays: number
  lastIncident: string
  pendingReview: number
  overnightFixed: number
  memoryEntries: number
  mttr: number
  successRate: number
  activeAgents: number
  healthHistory: boolean[]
}

export interface PendingIssue {
  id: string
  title: string
  severity: IssueSeverity
  patchCount: number
  status: PendingIssueStatus
}

export interface OvernightEvent {
  time: string
  title: string
  description: string
  result: 'success' | 'failed'
}

export interface CanaryStatus {
  issueId: string
  issueTitle: string
  currentStep: string
  steps: string[]
  metrics: CanaryMetrics
}
