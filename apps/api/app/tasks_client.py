"""Celery 客户端：API 仅按任务名入队，不 import worker 任务代码。"""

from __future__ import annotations

from celery import Celery
from clipmind_shared.constants import (
    QUEUE_SCAN,
    TASK_RESCAN_ASSET,
    TASK_SCAN_SOURCE_DIRECTORY,
)

from app.config import get_settings

_settings = get_settings()

celery_client = Celery(
    "clipmind-api-client",
    broker=_settings.celery_broker_url,
    backend=_settings.celery_result_backend,
)


def enqueue_scan(scan_run_id: int) -> str:
    """入队目录扫描任务，返回 celery_task_id。"""
    result = celery_client.send_task(
        TASK_SCAN_SOURCE_DIRECTORY, args=[scan_run_id], queue=QUEUE_SCAN
    )
    return result.id


def enqueue_rescan_asset(asset_id: int) -> str:
    """入队单素材重扫任务，返回 celery_task_id。"""
    result = celery_client.send_task(TASK_RESCAN_ASSET, args=[asset_id], queue=QUEUE_SCAN)
    return result.id
