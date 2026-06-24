"""Celery 应用定义。

PR-01 仅注册扫描任务，worker 仅消费 default + scan 队列。
media/ai/export 队列与 beat 调度为后续 PR 预留（不在 PR-01 运行）。
"""

from __future__ import annotations

from celery import Celery
from clipmind_shared.constants import QUEUE_DEFAULT

from clipmind_worker.config import get_settings

_settings = get_settings()

celery_app = Celery(
    "clipmind",
    broker=_settings.celery_broker_url,
    backend=_settings.celery_result_backend,
    include=["clipmind_worker.tasks.scan"],
)

celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_default_queue=QUEUE_DEFAULT,
    result_expires=3600,
    timezone="UTC",
    enable_utc=True,
    broker_transport_options={
        "visibility_timeout": 3600,
        "priority_steps": list(range(10)),
    },
)
