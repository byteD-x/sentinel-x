"""Static contract checks for the proposed/full PostgreSQL migration.

These tests intentionally do not connect to PostgreSQL. They protect the SQL
contract while the runtime PostgreSQL profile and integration environment are
still being built. SQLite local-profile tests remain separate.
"""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MIGRATION = ROOT / "migrations" / "versions" / "0001_domain.sql"
ROLLBACK = ROOT / "migrations" / "versions" / "0001_domain.down.sql"
README = ROOT / "migrations" / "README.md"


def _sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def _table_block(sql: str, table: str) -> str:
    match = re.search(
        rf"CREATE TABLE IF NOT EXISTS {re.escape(table)} \(.*?\n\);",
        sql,
        flags=re.IGNORECASE | re.DOTALL,
    )
    assert match, f"missing CREATE TABLE for {table}"
    return match.group(0)


def test_migration_is_explicitly_postgresql_and_local_profile_is_separate() -> None:
    sql = _sql()
    readme = README.read_text(encoding="utf-8")
    assert "profile: proposed/full-postgresql" in sql
    assert "local SQLite" in sql
    assert "PostgreSQL" in readme
    assert "SQLite" in readme
    assert "does not" in readme
    assert "PRAGMA" not in sql.upper()
    assert "AUTOINCREMENT" not in sql.upper()
    assert not re.search(r"^\s*CREATE\s+EXTENSION\b", sql, flags=re.IGNORECASE | re.MULTILINE)


def test_migration_has_transaction_and_required_relations() -> None:
    sql = _sql()
    assert sql.lstrip().startswith("--")
    assert re.search(r"\bBEGIN;", sql)
    assert re.search(r"\bCOMMIT;\s*$", sql)
    for table in (
        "incidents",
        "remediation_plans",
        "timeline_events",
        "approval_requests",
        "approval_decisions",
        "action_executions",
        "verification_results",
        "outbox_events",
    ):
        _table_block(sql, table)


def test_incident_state_and_dedup_contract() -> None:
    block = _table_block(_sql(), "incidents")
    for status in (
        "DETECTED",
        "TRIAGING",
        "DIAGNOSING",
        "PLAN_PROPOSED",
        "AWAITING_APPROVAL",
        "EXECUTING",
        "VERIFYING",
        "RESOLVED",
        "ESCALATED",
        "FAILED",
    ):
        assert f"'{status}'" in block
    assert "projection_version BIGINT NOT NULL DEFAULT 0" in block
    assert "workflow_id TEXT NOT NULL UNIQUE" in block
    sql = _sql()
    assert "incidents_active_fingerprint_uidx" in sql
    assert "WHERE status NOT IN ('RESOLVED', 'ESCALATED', 'FAILED')" in sql


def test_timeline_and_approval_are_append_only_and_idempotent() -> None:
    sql = _sql()
    timeline = _table_block(sql, "timeline_events")
    assert "sequence BIGINT NOT NULL" in timeline
    assert "UNIQUE (incident_id, sequence)" in timeline
    assert "UNIQUE (incident_id, workflow_event_id)" in timeline
    approvals = _table_block(sql, "approval_requests")
    assert "expires_at > created_at" in approvals
    assert "consumed_count <= max_executions" in approvals
    assert "approval_requests_pending_plan_hash_uidx" in sql
    decisions = _table_block(sql, "approval_decisions")
    assert "request_id UUID PRIMARY KEY" in decisions
    assert "decision IN ('approved', 'rejected')" in decisions
    assert "timeline_events_immutable" in sql
    assert "approval_decisions_immutable" in sql
    assert "REVOKE UPDATE, DELETE ON timeline_events FROM PUBLIC" in sql
    assert "REVOKE UPDATE, DELETE ON approval_decisions FROM PUBLIC" in sql


def test_action_and_verification_contract() -> None:
    sql = _sql()
    action = _table_block(sql, "action_executions")
    assert "idempotency_key_hash TEXT NOT NULL UNIQUE" in action
    for status in (
        "REGISTERED",
        "VALIDATING",
        "RUNNING",
        "RECONCILING",
        "SUCCEEDED",
        "REJECTED",
        "FAILED",
        "CANCELLED",
    ):
        assert f"'{status}'" in action
    assert "action_executions_target_active_uidx" in sql
    assert "target_uid TEXT NOT NULL" in action
    assert "target_observed_generation BIGINT NOT NULL" in action
    verification = _table_block(sql, "verification_results")
    assert "baseline_window JSONB NOT NULL" in verification
    assert "observed_window JSONB NOT NULL" in verification
    assert "metric TEXT NOT NULL" in verification
    assert "threshold JSONB NOT NULL" in verification
    assert "sli_results JSONB NOT NULL" in verification
    assert "passed BOOLEAN NOT NULL" in verification


def test_outbox_contract_supports_at_least_once_dispatch() -> None:
    sql = _sql()
    outbox = _table_block(sql, "outbox_events")
    for field in ("published_at", "available_at", "attempt_count", "last_error"):
        assert field in outbox
    assert "UNIQUE (aggregate_type, aggregate_id, sequence)" in outbox
    assert "outbox_events_unpublished_idx" in sql
    assert "WHERE published_at IS NULL" in sql


def test_rollback_is_reverse_order_and_explicitly_transactional() -> None:
    rollback = ROLLBACK.read_text(encoding="utf-8")
    assert rollback.lstrip().startswith("--")
    assert re.search(r"\bBEGIN;", rollback)
    assert re.search(r"\bCOMMIT;\s*$", rollback)
    positions = [rollback.index(f"DROP TABLE IF EXISTS {table};") for table in (
        "outbox_events",
        "verification_results",
        "action_executions",
        "approval_decisions",
        "approval_requests",
        "timeline_events",
        "remediation_plans",
        "incidents",
    )]
    assert positions == sorted(positions)
