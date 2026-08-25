-- Persist Alert Ingress nonce replay protection for full profile.

BEGIN;

CREATE TABLE IF NOT EXISTS alert_replay_nonces (
    nonce TEXT PRIMARY KEY CHECK (length(nonce) BETWEEN 1 AND 128),
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS alert_replay_nonces_expiry_idx
    ON alert_replay_nonces (expires_at);

COMMIT;
