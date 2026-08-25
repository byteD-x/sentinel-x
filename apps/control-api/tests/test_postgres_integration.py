"""真实 PostgreSQL migration 验证入口。

默认不自动连接开发者数据库；设置 ``SENTINEL_POSTGRES_ADMIN_URL`` 后运行本文件，
测试会调用临时数据库脚本并在 finally 中删除数据库。CI 未提供该变量时明确跳过。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


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
