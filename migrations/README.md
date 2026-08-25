# PostgreSQL migrations

This directory contains the proposed/full-profile PostgreSQL schema for the
Sentinel-X control plane. The migration is intentionally plain SQL: the
repository does not currently depend on Alembic, asyncpg, or a running
PostgreSQL service.

Apply `versions/0001_domain.sql` with a PostgreSQL migration runner in a
PostgreSQL environment only. `versions/0001_domain.down.sql` is a destructive
rollback for local development and must follow a backup/restore plan.

The local profile continues to use its existing SQLite snapshot/outbox and
SQLite approval store. It must not be described as an implementation of this
PostgreSQL schema. No migration in this directory creates extensions, roles,
credentials, or connections to a database.

The SQL is a schema contract, not evidence that the full PostgreSQL profile is
running. Runtime projection, dispatcher, Temporal reconciliation, and
integration tests remain separate work items.
