"""真实 PostgreSQL migration 验证入口。

默认不自动连接开发者数据库；设置 ``SENTINEL_POSTGRES_ADMIN_URL`` 后运行本文件，
测试会调用临时数据库脚本并在 finally 中删除数据库。CI 未提供该变量时明确跳过。
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import sentinel_x_control_api.app as control_app
from sentinel_x_control_api.app import AlertSource, IncidentCreate, InMemoryStore, PostgresStore
from sentinel_x_control_api.postgres import apply_migrations
from sentinel_x_control_api.postgres_dispatcher import PostgresOutboxDispatcher
from sentinel_x_control_api.postgres_repository import PostgresIncidentRepository


@pytest.mark.integration
def test_real_postgres_migration_round_trip(tmp_path: Path):
    admin_url = os.getenv("SENTINEL_POSTGRES_ADMIN_URL")
    if not admin_url:
        pytest.skip("未设置 SENTINEL_POSTGRES_ADMIN_URL")
    output = tmp_path / "postgres-migration.json"
    result = subprocess.run(
        [sys.executable, "scripts/verify_postgres_migrations.py", "--admin-url", admin_url, "--output", str(output)],
        text=True,
        capture_output=True,
        cwd=Path(__file__).resolve().parents[3],
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert '"passed": true' in output.read_text(encoding="utf-8")


@pytest.mark.integration
def test_real_repository_and_outbox_dispatcher():
    admin_url = os.getenv("SENTINEL_POSTGRES_ADMIN_URL")
    if not admin_url:
        pytest.skip("未设置 SENTINEL_POSTGRES_ADMIN_URL")
    psycopg = pytest.importorskip("psycopg")
    database = f"sentinel_x_repo_{uuid4().hex[:10]}"
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
        first = repository.create_incident(
            fingerprint="integration-fingerprint",
            severity="warning",
            service="inventory-api",
            workflow_id="incident/integration-1",
        )
        duplicate = repository.create_incident(
            fingerprint="integration-fingerprint",
            severity="warning",
            service="inventory-api",
            workflow_id="incident/integration-duplicate",
        )
        assert duplicate.id == first.id
        event = repository.append_event(
            incident_id=first.id,
            event_type="evidence.collected",
            actor_type="SYSTEM",
            payload={"source": "integration"},
            workflow_event_id="integration-event-2",
        )
        delivered = []
        dispatcher = PostgresOutboxDispatcher(
            lambda: psycopg.connect(database_url), delivered.append
        )
        assert dispatcher.dispatch_once() == 2
        assert {item.event_type for item in delivered} == {
            "incident.created",
            "evidence.collected",
        }
        assert event.sequence == 2
        assert dispatcher.dispatch_once() == 0
    finally:
        admin.execute(f'DROP DATABASE IF EXISTS "{database}"')
        admin.close()


@pytest.mark.integration
def test_control_api_full_lifespan_uses_postgres_store(monkeypatch):
    admin_url = os.getenv("SENTINEL_POSTGRES_ADMIN_URL")
    if not admin_url:
        pytest.skip("未设置 SENTINEL_POSTGRES_ADMIN_URL")
    psycopg = pytest.importorskip("psycopg")
    database = f"sentinel_x_api_{uuid4().hex[:10]}"
    admin = psycopg.connect(admin_url, autocommit=True)
    original_store = control_app.store
    original_workflow_store = control_app.local_workflow.store
    try:
        admin.execute(f'CREATE DATABASE "{database}"')
        database_url = admin_url.rsplit("/", 1)[0] + f"/{database}"
        monkeypatch.setenv("SENTINEL_PROFILE", "full")
        monkeypatch.setenv("DATABASE_URL", database_url)
        monkeypatch.setenv("LOCAL_SESSION_SIGNING_KEY", "integration-session")
        monkeypatch.setenv("ACTION_GATEWAY_URL", "http://gateway")
        monkeypatch.setenv("ALERT_INGRESS_HMAC_KEY", "integration-alert")
        with TestClient(control_app.app):
            assert isinstance(control_app.store, PostgresStore)
            incident = control_app.store.create_incident(
                IncidentCreate(
                    alert_source=AlertSource(
                        alertmanager_id="integration",
                        fingerprint="api-full-fingerprint",
                        alert_name="InventoryHighErrorRate",
                        severity="warning",
                        description="integration",
                        started_at=datetime.now(timezone.utc),
                    )
                )
            )
            with psycopg.connect(database_url) as connection:
                count = connection.execute(
                    "SELECT count(*) FROM incidents WHERE id = %s", (incident.id,)
                ).fetchone()[0]
            assert count == 1
            deadline = time.monotonic() + 3
            published = 0
            while time.monotonic() < deadline and published == 0:
                with psycopg.connect(database_url) as connection:
                    published = connection.execute(
                        "SELECT count(*) FROM outbox_events WHERE aggregate_id = %s AND published_at IS NOT NULL",
                        (incident.id,),
                    ).fetchone()[0]
                if published == 0:
                    time.sleep(0.1)
            assert published == 1
    finally:
        control_app.store = original_store
        control_app.local_workflow.store = original_workflow_store
        admin.execute(f'DROP DATABASE IF EXISTS "{database}"')
        admin.close()


@pytest.mark.integration
def test_postgres_store_rebuilds_incident_and_timeline_after_restart():
    admin_url = os.getenv("SENTINEL_POSTGRES_ADMIN_URL")
    if not admin_url:
        pytest.skip("未设置 SENTINEL_POSTGRES_ADMIN_URL")
    psycopg = pytest.importorskip("psycopg")
    database = f"sentinel_x_rebuild_{uuid4().hex[:10]}"
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
        record = repository.create_incident(
            fingerprint="restart-fingerprint",
            severity="critical",
            service="payment-api",
            workflow_id="incident/restart-1",
        )
        repository.append_event(
            incident_id=record.id,
            event_type="evidence.collected",
            actor_type="INVESTIGATOR",
            payload={"source": "postgres"},
            workflow_event_id="restart-event-2",
        )
        restored = control_app.PostgresStore(
            PostgresIncidentRepository(lambda: psycopg.connect(database_url))
        )
        incident = restored.get_incident(str(record.id))
        assert incident is not None
        assert incident.status.value == "DETECTED"
        assert incident.severity.value == "critical"
        assert [event.sequence for event in incident.timeline] == [1, 2]
        assert incident.timeline[1].event_type == "evidence.collected"
        assert incident.timeline[1].payload == {"source": "postgres"}
        restored.set_status(incident, control_app.IncidentStatus.TRIAGING, "restart test")
        restarted = control_app.PostgresStore(
            PostgresIncidentRepository(lambda: psycopg.connect(database_url))
        )
        recovered = restarted.get_incident(str(record.id))
        assert recovered is not None
        assert recovered.status == control_app.IncidentStatus.TRIAGING
        assert [event.sequence for event in recovered.timeline] == [1, 2, 3]
        assert recovered.timeline[-1].event_type == "incident.status_changed"
    finally:
        admin.execute(f'DROP DATABASE IF EXISTS "{database}"')
        admin.close()
