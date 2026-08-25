-- Sentinel-X full-profile request idempotency records
-- profile: full-postgresql

BEGIN;

CREATE TABLE IF NOT EXISTS idempotency_records (
    actor_key TEXT NOT NULL CHECK (length(actor_key) <= 512),
    route TEXT NOT NULL CHECK (length(route) BETWEEN 1 AND 512),
    idempotency_key TEXT NOT NULL CHECK (length(idempotency_key) BETWEEN 16 AND 128),
    body_hash TEXT NOT NULL CHECK (length(body_hash) = 64),
    status_code INTEGER NOT NULL DEFAULT 0 CHECK (status_code BETWEEN 0 AND 599),
    response_headers JSONB NOT NULL DEFAULT '{}'::jsonb,
    response_body BYTEA,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    PRIMARY KEY (actor_key, route, idempotency_key),
    CONSTRAINT idempotency_response_pair_check CHECK (
        (status_code = 0 AND response_body IS NULL AND completed_at IS NULL)
        OR (status_code > 0 AND response_body IS NOT NULL AND completed_at IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idempotency_records_created_idx
    ON idempotency_records (created_at);

COMMIT;
