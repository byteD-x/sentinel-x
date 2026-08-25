"""PostgreSQL migration 与健康检查边界。

该模块只负责连接和迁移元数据，不承载领域写入。领域事务、投影和
outbox dispatcher 由 repository/应用生命周期显式接入；full profile 不允许
在缺少驱动或数据库不可达时静默回退到 SQLite。
"""

from __future__ import annotations

import hashlib
import importlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


class PostgresRuntimeError(RuntimeError):
    """PostgreSQL runtime 无法安全初始化。"""


@dataclass(frozen=True)
class MigrationRecord:
    version: str
    checksum: str


def _load_psycopg() -> Any:
    try:
        return importlib.import_module("psycopg")
    except ImportError as exc:
        raise PostgresRuntimeError(
            "full profile 需要 psycopg；请安装 control-api 的 PostgreSQL 依赖"
        ) from exc


def _migration_files(migrations_dir: str | Path) -> list[Path]:
    directory = Path(migrations_dir) / "versions"
    files = sorted(path for path in directory.glob("*.sql") if not path.name.endswith(".down.sql"))
    if not files:
        raise PostgresRuntimeError(f"未找到 PostgreSQL migration: {directory}")
    return files


def _checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ensure_migration_table(cursor: Any) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS sentinel_schema_migrations (
            version TEXT PRIMARY KEY,
            checksum TEXT NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL
        )
        """
    )


def apply_migrations(
    database_url: str,
    *,
    migrations_dir: str | Path,
    connect: Callable[..., Any] | None = None,
) -> list[MigrationRecord]:
    """按文件名顺序执行 migration，并拒绝已应用文件被改写。"""

    if not database_url.startswith(("postgresql://", "postgresql+")):
        raise PostgresRuntimeError("migration runner 只接受 PostgreSQL DATABASE_URL")
    connect = connect or _load_psycopg().connect
    files = _migration_files(migrations_dir)
    try:
        connection = connect(database_url, autocommit=True)
    except Exception as exc:  # noqa: BLE001 - 连接边界统一收敛错误
        raise PostgresRuntimeError("PostgreSQL 连接失败，full profile 保持关闭") from exc

    applied: list[MigrationRecord] = []
    try:
        with connection.cursor() as cursor:
            _ensure_migration_table(cursor)
            for path in files:
                version = path.stem
                checksum = _checksum(path)
                cursor.execute(
                    "SELECT checksum FROM sentinel_schema_migrations WHERE version = %s",
                    (version,),
                )
                row = cursor.fetchone()
                if row is not None:
                    if row[0] != checksum:
                        raise PostgresRuntimeError(f"migration {version} checksum 不匹配")
                    applied.append(MigrationRecord(version, checksum))
                    continue
                cursor.execute(path.read_text(encoding="utf-8"))
                cursor.execute(
                    """
                    INSERT INTO sentinel_schema_migrations(version, checksum, applied_at)
                    VALUES (%s, %s, %s)
                    """,
                    (version, checksum, datetime.now(timezone.utc)),
                )
                applied.append(MigrationRecord(version, checksum))
    except PostgresRuntimeError:
        raise
    except Exception as exc:  # noqa: BLE001 - migration 边界统一收敛错误
        raise PostgresRuntimeError("PostgreSQL migration 执行失败") from exc
    finally:
        connection.close()
    return applied


def check_postgres_health(database_url: str, *, connect: Callable[..., Any] | None = None) -> None:
    """执行 SELECT 1；任何失败都抛出 fail-closed 错误。"""

    if not database_url.startswith(("postgresql://", "postgresql+")):
        raise PostgresRuntimeError("health check 只接受 PostgreSQL DATABASE_URL")
    connect = connect or _load_psycopg().connect
    try:
        connection = connect(database_url, autocommit=True)
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                if cursor.fetchone() != (1,):
                    raise PostgresRuntimeError("PostgreSQL health check 返回异常")
        finally:
            connection.close()
    except PostgresRuntimeError:
        raise
    except Exception as exc:  # noqa: BLE001 - 健康检查边界统一收敛错误
        raise PostgresRuntimeError("PostgreSQL health check 失败，full profile 保持关闭") from exc
