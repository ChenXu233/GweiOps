export type IssueSeverity = 'critical' | 'medium' | 'low'
export type IssueSource = 'github_issue' | 'prometheus' | 'trivy' | 'cve' | 'sentry'
export type IssueStatus = 'pending_review' | 'canary' | 'approved' | 'completed' | 'rolled_back'
export type PatchType = 'hotfix' | 'proper' | 'refactor' | 'upstream' | 'patch' | 'docs'
export type PatchRisk = 'low' | 'medium' | 'high'

export interface Patch {
  id: string
  type: PatchType
  risk: PatchRisk
  lines: number
  passRate: number
  latency: string
  description: string
  selected?: boolean
}

export interface CanaryProgress {
  current: string
  steps: string[]
  completedSteps: string[]
  metrics: {
    passRate: number
    errorRate: number
    p99Latency: string
    memoryPeak: string
  }
}

export interface TimelineStep {
  id: string
  label: string
  status: 'done' | 'active' | 'pending'
}

export interface Issue {
  id: string
  title: string
  source: IssueSource
  severity: IssueSeverity
  status: IssueStatus
  repo: string
  triggeredAt: string
  patches: Patch[]
  canary?: CanaryProgress
  timeline: TimelineStep[]
}
