"""数据库基座：声明式 Base、命名规范、UTC 时间、PG 枚举工厂。"""

from clipmind_shared.db.base import NAMING_CONVENTION, Base, pg_enum, utcnow

__all__ = ["Base", "NAMING_CONVENTION", "pg_enum", "utcnow"]
