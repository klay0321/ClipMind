"""Alembic 迁移往返测试（隔离临时数据库，需要 TEST_DATABASE_URL + 建库权限）。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
API_DIR = Path(__file__).resolve().parents[1]
TMP_DB = "clipmind_mig_test"


def _split_url(url: str) -> tuple[str, str]:
    base, dbname = url.rsplit("/", 1)
    return base, dbname


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="需要 TEST_DATABASE_URL")
def test_alembic_upgrade_downgrade_roundtrip():
    from sqlalchemy import create_engine, text

    base, _ = _split_url(TEST_DATABASE_URL)
    admin_url = base.replace("+asyncpg", "+psycopg") + "/postgres"

    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT", future=True)
    with admin.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {TMP_DB}"))
        conn.execute(text(f"CREATE DATABASE {TMP_DB}"))
    admin.dispose()

    tmp_async_url = f"{base}/{TMP_DB}"
    # PYTHONUTF8=1 让 alembic 在任意系统 locale 下按 UTF-8 读取配置文件
    env = {**os.environ, "DATABASE_URL": tmp_async_url, "PYTHONUTF8": "1"}

    def alembic(*args: str) -> subprocess.CompletedProcess[str]:
        # 用当前解释器运行 alembic 模块，避免依赖 PATH（本地 venv / CI 均稳定）
        return subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=API_DIR,
            env=env,
            capture_output=True,
            text=True,
        )

    try:
        up = alembic("upgrade", "head")
        assert up.returncode == 0, up.stderr
        down = alembic("downgrade", "base")
        assert down.returncode == 0, down.stderr
        up2 = alembic("upgrade", "head")
        assert up2.returncode == 0, up2.stderr
    finally:
        admin = create_engine(admin_url, isolation_level="AUTOCOMMIT", future=True)
        with admin.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {TMP_DB}"))
        admin.dispose()
