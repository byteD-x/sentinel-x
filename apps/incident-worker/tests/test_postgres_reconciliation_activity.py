from datetime import datetime, timezone
import os
from pathlib import Path
from uuid import uuid4

import pytest

from sentinel_x_incident_worker.activities import reconcile_postgres_projection


@pytest.mark.integration
@pytest.mark.asyncio
async def test_reconciliation_activity_reads_postgres_projection():
    admin_url = os.getenv("SENTINEL_POSTGRES_ADMIN_URL")
    if not admin_url:
        pytest.skip("未设置 SENTINEL_POSTGRES_ADMIN_URL")
    psycopg = pytest.importorskip("psycopg")
    from sentinel_x_control_api.postgres import apply_migrations
    from sentinel_x_control_api.postgres_repository import PostgresIncidentRepository

    database = f"sentinel_x_reconcile_{uuid4().hex[:10]}"
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
            fingerprint="reconcile-fingerprint",
            severity="warning",
            service="inventory-api",
            workflow_id="workflow/reconcile-1",
        )
        with psycopg.connect(database_url) as connection:
            connection.execute(
                "UPDATE incidents SET workflow_run_id = %s, workflow_event_id = %s, status = %s, projection_version = 3 WHERE id = %s",
                ("run/reconcile-1", "event/reconcile-3", "VERIFYING", str(incident.id)),
            )
        result = await reconcile_postgres_projection(
            incident_id=str(incident.id),
            expected={
                "workflow_run_id": "run/reconcile-1",
                "workflow_event_id": "event/reconcile-3",
                "status": "VERIFYING",
                "projection_version": 3,
            },
            database_url=database_url,
        )
        assert result["projection_version"] == 3
        assert result["status"] == "VERIFYING"
    finally:
        admin.execute(f'DROP DATABASE IF EXISTS "{database}"')
        admin.close()
