BEGIN;

CREATE TABLE IF NOT EXISTS workflow_checkpoints (
    incident_id UUID PRIMARY KEY REFERENCES incidents(id) ON DELETE CASCADE,
    workflow_id TEXT NOT NULL UNIQUE CHECK (length(workflow_id) BETWEEN 1 AND 256),
    scenario_id TEXT NOT NULL CHECK (length(scenario_id) BETWEEN 1 AND 256),
    phase TEXT NOT NULL CHECK (length(phase) BETWEEN 1 AND 64),
    action_execution_id TEXT,
    completed BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS workflow_checkpoints_resumable_idx
    ON workflow_checkpoints (completed, updated_at)
    WHERE completed = FALSE;

COMMIT;
