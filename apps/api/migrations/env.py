"""Alembic 环境配置。

- 同步连接串来自应用配置（asyncpg -> psycopg）。
- target_metadata 取自共享层的 Base.metadata（import models 触发注册）。
- include_object 跳过手工维护的部分唯一索引，保持 autogenerate 干净。
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


def include_object(obj, name, type_, reflected, compare_to) -> bool:  # noqa: ANN001
    # 部分唯一索引手工维护，跳过 autogenerate 比对避免噪音
    if type_ == "index" and name == "uq_active_scan_run":
        return False
    return True


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
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
            include_object=include_object,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
