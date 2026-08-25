-- Preserve ActionExecution metadata needed for restart-safe API recovery.

BEGIN;

ALTER TABLE action_executions
    ADD COLUMN IF NOT EXISTS runbook_ref TEXT NOT NULL DEFAULT 'restart_deployment@1'
        CHECK (length(runbook_ref) BETWEEN 1 AND 128);

ALTER TABLE action_executions
    ADD COLUMN IF NOT EXISTS idempotency_key TEXT
        CHECK (idempotency_key IS NULL OR length(idempotency_key) BETWEEN 16 AND 256);

CREATE UNIQUE INDEX IF NOT EXISTS action_executions_idempotency_key_uidx
    ON action_executions (idempotency_key)
    WHERE idempotency_key IS NOT NULL;

COMMIT;
