"""Alembic 环境配置。

- 同步连接串来自应用配置（asyncpg -> psycopg）。
- target_metadata 取自共享层的 Base.metadata（import models 触发注册）。
- 部分唯一索引（uq_active_scan_run / uq_active_media_run）通过模型上正确声明
  `postgresql_where=text("status IN (...)")` 与迁移自然一致，Alembic 能正确比对
  其 WHERE 子句，无需 include_object 特殊跳过（compare_type=True 保留类型比对）。
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context

# import 全部模型以填充 metadata
from clipmind_shared.models import Base  # noqa: E402
from sqlalchemy import engine_from_config, pool

from app.config import get_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.sync_database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
