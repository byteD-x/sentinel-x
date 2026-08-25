-- Full-profile local rollback for the idempotency migration.

BEGIN;
DROP TABLE IF EXISTS idempotency_records;
COMMIT;
