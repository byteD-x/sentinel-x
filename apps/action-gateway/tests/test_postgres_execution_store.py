from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from sentinel_x_action_gateway.app import PostgresExecutionStore, StoredExecution
from sentinel_x_action_gateway.approval_store import TargetIdentity


@pytest.mark.integration
def test_postgres_execution_store_persists_idempotency_and_status():
    admin_url = os.getenv("SENTINEL_POSTGRES_ADMIN_URL")
    if not admin_url:
        pytest.skip("未设置 SENTINEL_POSTGRES_ADMIN_URL")
    psycopg = pytest.importorskip("psycopg")
    from sentinel_x_control_api.postgres import apply_migrations
    from sentinel_x_control_api.postgres_repository import PostgresIncidentRepository

    database = f"sentinel_x_execution_{uuid4().hex[:10]}"
    admin = psycopg.connect(admin_url, autocommit=True)
    try:
        admin.execute(f'CREATE DATABASE "{database}"')
        database_url = admin_url.rsplit("/", 1)[0] + f"/{database}"
        apply_migrations(
            database_url,
            migrations_dir=Path(__file__).resolve().parents[3] / "migrations",
            connect=lambda *args, **kwargs: psycopg.connect(database_url, **kwargs),
        )
        repository = PostgresIncidentRepository(lambda: psycopg.connect(database_url))
        incident = repository.create_incident(
            fingerprint="execution-fingerprint",
            severity="warning",
            service="payment-api",
            workflow_id="incident/execution-1",
        )
        plan = repository.create_approval(
            incident_id=incident.id,
            plan_hash="execution-plan-hash-1",
            client_plan_id="plan-execution-1",
            runbook_ref="restart_deployment@1",
            target="payment-api",
            parameters={"reason": "execution integration"},
            risk_level="R1",
            policy_version="mvp@1",
            target_namespace="demo-shop",
            target_kind="Deployment",
            target_name="payment-api",
            target_uid="fake-payment-api",
            target_observed_generation=1,
            target_resource_version="rv-1",
            rationale="execution integration",
            hypothesis_id="hyp-execution-1",
            expires_at=datetime.now(UTC) + timedelta(minutes=30),
        )
        store = PostgresExecutionStore(lambda: psycopg.connect(database_url))
        execution = StoredExecution(
            execution_id=str(uuid4()), approval_id=plan["id"],
            incident_id=str(incident.id), plan_id=plan["db_plan_id"],
            status="running", runbook_ref="restart_deployment@1", target="payment-api",
            idempotency_key="idempotency-execution-1", before_state="before",
            started_at=datetime.now(UTC), execution_mode="fake-k8s",
            target_identity=TargetIdentity(
                namespace="demo-shop", kind="Deployment", name="payment-api",
                uid="fake-payment-api", generation=1,
            ),
        )
        store.create(execution)
        assert store.check_idempotency(execution.idempotency_key).execution_id == execution.execution_id
        store.update(execution.execution_id, status="succeeded", after_state="after")
        restarted = PostgresExecutionStore(lambda: psycopg.connect(database_url))
        restored = restarted.get(execution.execution_id)
        assert restored is not None
        assert restored.status == "succeeded"
        assert restored.runbook_ref == "restart_deployment@1"
        assert restored.idempotency_key == "idempotency-execution-1"
        assert restored.after_state == "after"
    finally:
        admin.execute(f'DROP DATABASE IF EXISTS "{database}"')
        admin.close()
