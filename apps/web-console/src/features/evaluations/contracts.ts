export interface EvaluationMetadata {
  commit_sha: string | null
  profile: string
  environment_ref: string
  hardware_ref: string | null
  dataset_ref: string
  model_ref: string
  policy_ref: string | null
  prompt_ref: string | null
  random_seed: number
  runs_per_scenario: number
  timeout_seconds: number
}

export interface EvaluationComparability {
  comparable: boolean
  baseline_ref: string | null
  reasons: string[]
}

export interface EvaluationMetric {
  name: string
  category: string
  value: number
  unit: string
  target: number | null
  direction: 'higher_is_better' | 'lower_is_better'
  passed: boolean | null
  sample_count?: number
}

export interface EvaluationAggregate {
  attempted_runs: number
  completed_runs: number
  failed_runs: number
  metrics: EvaluationMetric[]
}

export interface EvaluationArtifact {
  sha256: string
  size_bytes: number
  media_type: string
}

export interface ValidEvaluationSummary {
  report_id: string
  created_at: string
  archive_status: 'valid'
  metadata: EvaluationMetadata
  comparability: EvaluationComparability
  aggregate: EvaluationAggregate
  artifact: EvaluationArtifact
}

export interface InvalidEvaluationSummary {
  report_id: string
  archive_status: 'invalid'
  error: {
    code: string
    message: string
  }
}

export type EvaluationSummary = ValidEvaluationSummary | InvalidEvaluationSummary

export interface EvaluationListResponse {
  available: boolean
  unavailable_reason?: string
  items: EvaluationSummary[]
}

export interface EvaluationRun {
  run_id: string
  scenario_ref: string
  run_index: number
  incident_id: string
  model_ref: string
  config: Record<string, string | number | boolean | null>
  metrics: EvaluationMetric[]
}

export interface EvaluationFailure {
  scenario_ref: string
  run_index: number
  category: string
  code: string
  message: string
}

export interface EvaluationReport {
  schema_version: '1.0'
  report_id: string
  created_at: string
  metadata: EvaluationMetadata
  comparability: EvaluationComparability
  aggregate: EvaluationAggregate
  runs: EvaluationRun[]
  failures: EvaluationFailure[]
}

export interface EvaluationDetailResponse {
  report: EvaluationReport
  artifact: EvaluationArtifact
}
