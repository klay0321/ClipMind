"""SQLAlchemy 声明式基座。

- 统一命名规范，保证 Alembic autogenerate 的约束名稳定。
- 同一份 metadata 供 API（async 引擎）与 worker（sync 引擎）共享。
- 时间统一使用 UTC、timezone-aware。
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum as PyEnum

from sqlalchemy import Enum as SAEnum
from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# 约束/索引命名规范（跨迁移稳定）
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def utcnow() -> datetime:
    """timezone-aware 的当前 UTC 时间。"""
    return datetime.now(timezone.utc)


def pg_enum(enum_cls: type[PyEnum], name: str) -> SAEnum:
    """构造原生 PostgreSQL 枚举列类型。

    使用 values_callable 让数据库存储枚举的 value（小写字符串），
    而非默认的成员名（大写）。
    """
    return SAEnum(
        enum_cls,
        name=name,
        native_enum=True,
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
    )
