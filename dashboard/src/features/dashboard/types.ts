export type SystemStatus = 'healthy' | 'warning' | 'critical'

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
  severity: 'critical' | 'medium' | 'low'
  patchCount: number
  status: string
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
  metrics: {
    passRate: number
    errorRate: number
    p99Latency: string
    memoryPeak: string
  }
}
