-- Full-profile local rollback for ActionExecution metadata.

BEGIN;
DROP INDEX IF EXISTS action_executions_idempotency_key_uidx;
ALTER TABLE action_executions DROP COLUMN IF EXISTS idempotency_key;
ALTER TABLE action_executions DROP COLUMN IF EXISTS runbook_ref;
COMMIT;
