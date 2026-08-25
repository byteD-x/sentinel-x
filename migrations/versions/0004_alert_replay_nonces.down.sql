-- Full-profile local rollback for Alert Ingress replay protection.

BEGIN;
DROP TABLE IF EXISTS alert_replay_nonces;
COMMIT;
