-- Sentinel-X PostgreSQL schema
-- profile: proposed/full-postgresql
-- local SQLite is a separate local-only persistence implementation.
-- This migration does not create extensions or database roles.

BEGIN;

CREATE TABLE IF NOT EXISTS remediation_plans (
    id UUID PRIMARY KEY,
    incident_id UUID NOT NULL,
    runbook_id TEXT NOT NULL,
    runbook_version INTEGER NOT NULL CHECK (runbook_version > 0),
    runbook_hash TEXT NOT NULL CHECK (length(runbook_hash) <= 256),
    risk_level TEXT NOT NULL CHECK (risk_level IN ('R0', 'R1', 'R2', 'R3')),
    policy_version TEXT NOT NULL CHECK (length(policy_version) BETWEEN 1 AND 128),
    target_namespace TEXT NOT NULL CHECK (length(target_namespace) BETWEEN 1 AND 253),
    target_kind TEXT NOT NULL CHECK (length(target_kind) BETWEEN 1 AND 63),
    target_name TEXT NOT NULL CHECK (length(target_name) BETWEEN 1 AND 253),
    target_uid TEXT NOT NULL CHECK (length(target_uid) BETWEEN 1 AND 256),
    target_observed_generation BIGINT NOT NULL CHECK (target_observed_generation >= 0),
    target_resource_version TEXT NOT NULL CHECK (length(target_resource_version) <= 256),
    parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
    rationale TEXT NOT NULL CHECK (length(rationale) <= 8192),
    evidence_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    canonical_payload JSONB NOT NULL,
    plan_hash TEXT NOT NULL UNIQUE CHECK (length(plan_hash) BETWEEN 1 AND 256),
    status TEXT NOT NULL DEFAULT 'PROPOSED'
        CHECK (status IN ('PROPOSED', 'APPROVED', 'SUPERSEDED', 'REJECTED', 'EXECUTED')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    superseded_at TIMESTAMPTZ,
    CONSTRAINT remediation_plans_runbook_key UNIQUE (runbook_id, runbook_version, runbook_hash)
);

CREATE TABLE IF NOT EXISTS incidents (
    id UUID PRIMARY KEY,
    workflow_id TEXT NOT NULL UNIQUE CHECK (length(workflow_id) BETWEEN 1 AND 256),
    alert_fingerprint TEXT NOT NULL CHECK (length(alert_fingerprint) BETWEEN 1 AND 512),
    status TEXT NOT NULL CHECK (status IN (
        'DETECTED', 'TRIAGING', 'DIAGNOSING', 'PLAN_PROPOSED',
        'AWAITING_APPROVAL', 'EXECUTING', 'VERIFYING',
        'RESOLVED', 'ESCALATED', 'FAILED'
    )),
    severity TEXT NOT NULL CHECK (severity IN ('critical', 'warning', 'info')),
    service TEXT NOT NULL CHECK (length(service) BETWEEN 1 AND 253),
    exercise_run_id UUID,
    projection_version BIGINT NOT NULL DEFAULT 0 CHECK (projection_version >= 0),
    workflow_run_id TEXT CHECK (workflow_run_id IS NULL OR length(workflow_run_id) <= 256),
    workflow_event_id TEXT CHECK (workflow_event_id IS NULL OR length(workflow_event_id) <= 256),
    opened_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at TIMESTAMPTZ,
    close_reason TEXT CHECK (close_reason IS NULL OR length(close_reason) <= 4096),
    CONSTRAINT incidents_closed_state_check CHECK (
        (closed_at IS NULL AND status NOT IN ('RESOLVED', 'ESCALATED', 'FAILED'))
        OR (closed_at IS NOT NULL AND status IN ('RESOLVED', 'ESCALATED', 'FAILED'))
    )
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'remediation_plans_incident_fk'
    ) THEN
        ALTER TABLE remediation_plans
            ADD CONSTRAINT remediation_plans_incident_fk
            FOREIGN KEY (incident_id) REFERENCES incidents(id) ON DELETE RESTRICT;
    END IF;
END;
$$;

CREATE INDEX IF NOT EXISTS incidents_status_updated_idx
    ON incidents (status, updated_at DESC);
CREATE INDEX IF NOT EXISTS incidents_service_opened_idx
    ON incidents (service, opened_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS incidents_active_fingerprint_uidx
    ON incidents (alert_fingerprint)
    WHERE status NOT IN ('RESOLVED', 'ESCALATED', 'FAILED');

CREATE TABLE IF NOT EXISTS timeline_events (
    id UUID PRIMARY KEY,
    incident_id UUID NOT NULL REFERENCES incidents(id) ON DELETE RESTRICT,
    sequence BIGINT NOT NULL CHECK (sequence > 0),
    event_type TEXT NOT NULL CHECK (length(event_type) BETWEEN 1 AND 128),
    schema_version TEXT NOT NULL CHECK (length(schema_version) BETWEEN 1 AND 32),
    actor_type TEXT NOT NULL CHECK (actor_type IN (
        'SYSTEM', 'INVESTIGATOR', 'APPROVER', 'SCENARIO_RUNNER', 'WORKFLOW', 'USER'
    )),
    actor_id TEXT CHECK (actor_id IS NULL OR length(actor_id) <= 256),
    payload_ref JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at TIMESTAMPTZ NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    correlation_id TEXT CHECK (correlation_id IS NULL OR length(correlation_id) <= 256),
    workflow_event_id TEXT,
    CONSTRAINT timeline_events_sequence_uidx UNIQUE (incident_id, sequence),
    CONSTRAINT timeline_events_workflow_event_uidx UNIQUE (incident_id, workflow_event_id)
);

CREATE INDEX IF NOT EXISTS timeline_events_incident_sequence_idx
    ON timeline_events (incident_id, sequence);

CREATE TABLE IF NOT EXISTS approval_requests (
    id UUID PRIMARY KEY,
    incident_id UUID NOT NULL REFERENCES incidents(id) ON DELETE RESTRICT,
    plan_id UUID NOT NULL REFERENCES remediation_plans(id) ON DELETE RESTRICT,
    plan_hash TEXT NOT NULL CHECK (length(plan_hash) BETWEEN 1 AND 256),
    risk_level TEXT NOT NULL CHECK (risk_level IN ('R0', 'R1', 'R2', 'R3')),
    policy_version TEXT NOT NULL CHECK (length(policy_version) BETWEEN 1 AND 128),
    nonce_hash TEXT NOT NULL CHECK (length(nonce_hash) BETWEEN 1 AND 256),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected', 'expired', 'revoked')),
    expires_at TIMESTAMPTZ NOT NULL,
    max_executions INTEGER NOT NULL DEFAULT 1 CHECK (max_executions BETWEEN 1 AND 10),
    consumed_count INTEGER NOT NULL DEFAULT 0 CHECK (
        consumed_count >= 0 AND consumed_count <= max_executions
    ),
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    version BIGINT NOT NULL DEFAULT 1 CHECK (version > 0),
    CONSTRAINT approval_requests_expiry_check CHECK (expires_at > created_at),
    CONSTRAINT approval_requests_plan_hash_fk CHECK (plan_hash <> '')
);

CREATE UNIQUE INDEX IF NOT EXISTS approval_requests_pending_plan_hash_uidx
    ON approval_requests (plan_hash)
    WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS approval_requests_pending_expiry_idx
    ON approval_requests (status, expires_at);

CREATE TABLE IF NOT EXISTS approval_decisions (
    request_id UUID PRIMARY KEY REFERENCES approval_requests(id) ON DELETE RESTRICT,
    approver_id TEXT NOT NULL CHECK (length(approver_id) BETWEEN 1 AND 256),
    decision TEXT NOT NULL CHECK (decision IN ('approved', 'rejected')),
    reason TEXT NOT NULL CHECK (length(reason) <= 4096),
    decided_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    request_version BIGINT NOT NULL CHECK (request_version > 0)
);

CREATE TABLE IF NOT EXISTS action_executions (
    id UUID PRIMARY KEY,
    incident_id UUID NOT NULL REFERENCES incidents(id) ON DELETE RESTRICT,
    plan_id UUID NOT NULL REFERENCES remediation_plans(id) ON DELETE RESTRICT,
    approval_id UUID NOT NULL REFERENCES approval_requests(id) ON DELETE RESTRICT,
    idempotency_key_hash TEXT NOT NULL UNIQUE CHECK (length(idempotency_key_hash) BETWEEN 1 AND 256),
    status TEXT NOT NULL DEFAULT 'REGISTERED'
        CHECK (status IN (
            'REGISTERED', 'VALIDATING', 'RUNNING', 'RECONCILING',
            'SUCCEEDED', 'REJECTED', 'FAILED', 'CANCELLED'
        )),
    target_namespace TEXT NOT NULL CHECK (length(target_namespace) BETWEEN 1 AND 253),
    target_kind TEXT NOT NULL CHECK (length(target_kind) BETWEEN 1 AND 63),
    target_name TEXT NOT NULL CHECK (length(target_name) BETWEEN 1 AND 253),
    target_uid TEXT NOT NULL CHECK (length(target_uid) BETWEEN 1 AND 256),
    target_observed_generation BIGINT NOT NULL CHECK (target_observed_generation >= 0),
    target_resource_version TEXT NOT NULL CHECK (length(target_resource_version) <= 256),
    before_state_ref JSONB,
    before_state_hash TEXT CHECK (before_state_hash IS NULL OR length(before_state_hash) <= 256),
    after_state_ref JSONB,
    after_state_hash TEXT CHECK (after_state_hash IS NULL OR length(after_state_hash) <= 256),
    error_code TEXT CHECK (error_code IS NULL OR length(error_code) <= 128),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    reconciliation_count INTEGER NOT NULL DEFAULT 0 CHECK (reconciliation_count >= 0),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    version BIGINT NOT NULL DEFAULT 1 CHECK (version > 0),
    CONSTRAINT action_executions_finish_check CHECK (
        finished_at IS NULL OR started_at IS NOT NULL
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS action_executions_target_active_uidx
    ON action_executions (target_namespace, target_kind, target_name)
    WHERE status IN ('REGISTERED', 'VALIDATING', 'RUNNING', 'RECONCILING');
CREATE INDEX IF NOT EXISTS action_executions_incident_started_idx
    ON action_executions (incident_id, started_at DESC);

CREATE TABLE IF NOT EXISTS verification_results (
    id UUID PRIMARY KEY,
    incident_id UUID NOT NULL REFERENCES incidents(id) ON DELETE RESTRICT,
    action_execution_id UUID REFERENCES action_executions(id) ON DELETE RESTRICT,
    trigger_type TEXT NOT NULL CHECK (trigger_type IN (
        'ACTION', 'SCENARIO_RUNNER', 'WORKFLOW', 'MANUAL'
    )),
    trigger_ref TEXT CHECK (trigger_ref IS NULL OR length(trigger_ref) <= 256),
    recovery_actor TEXT NOT NULL CHECK (recovery_actor IN (
        'AI_REMEDIATION', 'SCENARIO_RUNNER', 'HUMAN', 'UNKNOWN'
    )),
    slo_policy_version TEXT NOT NULL CHECK (length(slo_policy_version) BETWEEN 1 AND 128),
    baseline_window JSONB NOT NULL,
    observed_window JSONB NOT NULL,
    sli_results JSONB NOT NULL,
    passed BOOLEAN NOT NULL,
    failure_reason TEXT CHECK (failure_reason IS NULL OR length(failure_reason) <= 4096),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS verification_results_incident_created_idx
    ON verification_results (incident_id, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS verification_results_passed_incident_uidx
    ON verification_results (incident_id)
    WHERE passed;

CREATE TABLE IF NOT EXISTS outbox_events (
    id UUID PRIMARY KEY,
    aggregate_type TEXT NOT NULL CHECK (length(aggregate_type) BETWEEN 1 AND 64),
    aggregate_id UUID NOT NULL,
    sequence BIGINT NOT NULL CHECK (sequence > 0),
    event_type TEXT NOT NULL CHECK (length(event_type) BETWEEN 1 AND 128),
    schema_version TEXT NOT NULL CHECK (length(schema_version) BETWEEN 1 AND 32),
    actor_type TEXT NOT NULL CHECK (length(actor_type) BETWEEN 1 AND 64),
    actor_id TEXT CHECK (actor_id IS NULL OR length(actor_id) <= 256),
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at TIMESTAMPTZ,
    available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    last_error TEXT CHECK (last_error IS NULL OR length(last_error) <= 4096),
    CONSTRAINT outbox_events_aggregate_sequence_uidx
        UNIQUE (aggregate_type, aggregate_id, sequence)
);

CREATE INDEX IF NOT EXISTS outbox_events_unpublished_idx
    ON outbox_events (available_at, created_at)
    WHERE published_at IS NULL;

CREATE OR REPLACE FUNCTION sentinel_x_reject_audit_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'immutable audit relation: %', TG_TABLE_NAME
        USING ERRCODE = '42501';
END;
$$;

DROP TRIGGER IF EXISTS timeline_events_immutable ON timeline_events;
CREATE TRIGGER timeline_events_immutable
    BEFORE UPDATE OR DELETE ON timeline_events
    FOR EACH ROW EXECUTE FUNCTION sentinel_x_reject_audit_mutation();

DROP TRIGGER IF EXISTS approval_decisions_immutable ON approval_decisions;
CREATE TRIGGER approval_decisions_immutable
    BEFORE UPDATE OR DELETE ON approval_decisions
    FOR EACH ROW EXECUTE FUNCTION sentinel_x_reject_audit_mutation();

-- The application role is provisioned outside migrations. Public clients must
-- never mutate append-only audit records; a dedicated role may INSERT/SELECT.
REVOKE UPDATE, DELETE ON timeline_events FROM PUBLIC;
REVOKE UPDATE, DELETE ON approval_decisions FROM PUBLIC;

COMMIT;
