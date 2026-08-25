-- Destructive rollback for 0001_domain.sql. Back up PostgreSQL first.
BEGIN;

DROP TRIGGER IF EXISTS approval_decisions_immutable ON approval_decisions;
DROP TRIGGER IF EXISTS timeline_events_immutable ON timeline_events;

DROP TABLE IF EXISTS outbox_events;
DROP TABLE IF EXISTS verification_results;
DROP TABLE IF EXISTS action_executions;
DROP TABLE IF EXISTS approval_decisions;
DROP TABLE IF EXISTS approval_requests;
DROP TABLE IF EXISTS timeline_events;
DROP TABLE IF EXISTS remediation_plans;
DROP TABLE IF EXISTS incidents;

DROP FUNCTION IF EXISTS sentinel_x_reject_audit_mutation();

COMMIT;
