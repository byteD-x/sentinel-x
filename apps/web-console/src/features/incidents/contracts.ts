export type IncidentStatus =
  | 'DETECTED'
  | 'TRIAGING'
  | 'DIAGNOSING'
  | 'PLAN_PROPOSED'
  | 'AWAITING_APPROVAL'
  | 'EXECUTING'
  | 'VERIFYING'
  | 'RESOLVED'
  | 'ESCALATED'
  | 'FAILED'

export type IncidentSeverity = 'critical' | 'warning' | 'info'
export type IncidentPhase = 'detect' | 'investigate' | 'plan' | 'approve' | 'execute' | 'verify'
export type MilestoneState = 'complete' | 'current' | 'upcoming' | 'failed'
export type MilestoneSourceKind = 'alert' | 'evidence' | 'hypothesis' | 'plan' | 'approval' | 'action' | 'verification'
export type SourceMode = 'fixture' | 'observed'

export interface EnvironmentBoundary {
  profile: string
  data_scope: string
  source_mode: SourceMode
}

export interface ImpactSummary {
  summary: string
  observed_at: string
  source_mode: SourceMode
}

export interface HypothesisSummary {
  statement: string
  confidence: number | null
  supporting_evidence_count: number
  opposing_evidence: string | null
  source_mode: SourceMode
}

export interface NextDecision {
  kind: 'investigate' | 'review_approval' | 'wait_execution' | 'review_verification' | 'escalated' | 'failed' | 'none'
  title: string
  reason: string
  target_href: string | null
}

export interface ApprovalSummary {
  id: string
  runbook_ref: string
  target: string
  risk_level: 'R0' | 'R1' | 'R2' | 'R3'
  plan_hash: string
  expires_at: string
}

export interface VerificationSummary {
  passed: boolean
  window_seconds: number | null
  recovery_actor: string | null
  source_mode: SourceMode
}

export interface IncidentCapabilities {
  can_decide_approval: boolean
  can_view_raw_evidence: boolean
  denial_reason: string | null
}

export interface IncidentMilestone {
  id: string
  phase: IncidentPhase
  state: MilestoneState
  occurred_at: string
  summary: string
  evidence_refs: string[]
  source_kind: MilestoneSourceKind
  source_mode: SourceMode
}

export interface IncidentOverview {
  id: string
  fingerprint: string | null
  status: IncidentStatus
  severity: IncidentSeverity
  alert_name: string
  description: string
  created_at: string
  updated_at: string
  resolved_at: string | null
  workflow_id: string | null
  version: number
  environment: EnvironmentBoundary
  impact: ImpactSummary | null
  top_hypothesis: HypothesisSummary | null
  next_decision: NextDecision
  active_approval: ApprovalSummary | null
  latest_verification: VerificationSummary | null
  capabilities: IncidentCapabilities
  milestones: IncidentMilestone[]
}
