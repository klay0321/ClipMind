"""Celery 应用定义。

worker 消费 default + scan 队列（扫描任务）；media-worker 消费 media 队列
（PR-02 拆镜头/派生/导出任务）；ai-worker 消费 ai 队列（PR-03A）；search-worker 消费
search 队列（PR-04 检索文档索引/嵌入）。export 队列与 beat 调度为后续 PR 预留。
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
    include=[
        "clipmind_worker.tasks.scan",
        "clipmind_worker.media.tasks",  # PR-02 拆镜头/派生/导出
        "clipmind_worker.ai.tasks",  # PR-03A AI 理解分析
        "clipmind_worker.search.tasks",  # PR-04 检索文档索引/嵌入
    ],
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
