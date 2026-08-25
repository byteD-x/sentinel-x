# PostgreSQL migrations

This directory contains the full-profile PostgreSQL schema for the Sentinel-X
control plane. The migration is intentionally plain SQL and is executed by
`scripts/migrate_postgres.py`, which records checksums in
`sentinel_schema_migrations` and fails closed on checksum drift.

Apply the migration with `python scripts/migrate_postgres.py --database-url ...`
in a PostgreSQL environment only. `versions/0001_domain.down.sql` is a destructive
rollback for local development and must follow a backup/restore plan.

The local profile continues to use its existing SQLite snapshot/outbox and
SQLite approval store. It must not be described as an implementation of this
PostgreSQL schema. No migration in this directory creates extensions, roles,
credentials, or connections to a database.

The runner and unit tests are implemented, but this repository currently has
no PostgreSQL service in the local verification environment. Runtime domain
repository, projection/dispatcher, Temporal reconciliation, and live database
integration evidence remain separate work items.
The local profile does not implement this PostgreSQL schema and does not silently
fall back to it when the full-profile database is unavailable.
