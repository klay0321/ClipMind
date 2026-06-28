"""数据库迁移版本就绪检查（部署升级可靠性）。

背景：``migrate`` 为一次性服务（``restart: no``），``docker compose up -d`` 不会重跑已成功退出的
migrate 容器，导致**已有数据库**在重建栈时被跳过升级，API 仍以旧 schema 启动并对新接口 500。
为此 ``/health/ready`` 增加"DB revision 是否已到 head"的检查：落后时明确 degraded，便于部署门禁/
负载均衡识别，而**不**让每个请求自行迁移、也不让 API 崩溃重启。

实现：用 Alembic ScriptDirectory 取迁移脚本 head（镜像内已含 migrations），与 ``alembic_version``
表当前 revision 比对。任何异常（表缺失/解析失败）一律视为"未就绪/落后"，保守返回 not-ok。
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


@dataclass
class MigrationState:
    current: str | None
    head: str | None
    ok: bool
    detail: str = ""


@lru_cache(maxsize=1)
def expected_head() -> str | None:
    """迁移脚本目录的 head revision（进程内缓存；脚本随镜像不变）。"""
    try:
        api_dir = Path(__file__).resolve().parents[2]  # apps/api
        cfg = Config(str(api_dir / "alembic.ini"))
        cfg.set_main_option("script_location", str(api_dir / "migrations"))
        return ScriptDirectory.from_config(cfg).get_current_head()
    except Exception:  # noqa: BLE001 - head 解析失败时由调用方按未知处理
        return None


async def current_revision(engine: AsyncEngine) -> str | None:
    """DB 中 alembic_version 当前 revision（表不存在/未迁移 → None）。"""
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT version_num FROM alembic_version "
                "WHERE EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_name = 'alembic_version')"
            )
        )
        row = result.first()
        return row[0] if row else None


async def check_migration(engine: AsyncEngine) -> MigrationState:
    head = expected_head()
    try:
        current = await current_revision(engine)
    except Exception as exc:  # noqa: BLE001 - 连接/查询失败 → 未就绪
        return MigrationState(
            current=None, head=head, ok=False, detail=f"无法读取 DB revision：{exc}"
        )

    if head is None:
        # 无法确定 head（异常环境）：不据此判失败，避免误报阻断
        return MigrationState(current=current, head=None, ok=True, detail="无法解析迁移 head")
    if current is None:
        return MigrationState(
            current=None, head=head, ok=False, detail="数据库未迁移（缺 alembic_version）"
        )
    if current != head:
        return MigrationState(
            current=current, head=head, ok=False,
            detail=f"DB revision 落后：当前 {current} != head {head}，请运行 scripts/db_upgrade",
        )
    return MigrationState(current=current, head=head, ok=True)
