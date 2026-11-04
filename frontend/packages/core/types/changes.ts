// packages/core/types/changes.ts
export type ChangeVerdict =
  | 'pending'
  | 'kept'
  | 'rolled_back'
  | 'blocked'
  | 'vetoed'
  | 'irreversible'

export interface ChangeRow {
  id: string
  created_at: string
  verdict: ChangeVerdict
  reason: string
  binding: string
  tenant: string
  handle: string | null
  idempotency_key: string
  intent: { summary?: string }
  effect: { capability?: string; task?: string }
}

export interface ChangeList {
  items: ChangeRow[]
  total: number
}
