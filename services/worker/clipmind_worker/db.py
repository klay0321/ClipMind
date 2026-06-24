"""Worker 同步数据库引擎与会话。"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from clipmind_worker.config import get_settings

_settings = get_settings()

engine = create_engine(
    _settings.sync_database_url,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
