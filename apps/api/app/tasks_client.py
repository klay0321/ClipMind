"""Celery 客户端：API 仅按任务名入队，不 import worker 任务代码。"""

from __future__ import annotations

from celery import Celery
from clipmind_shared.constants import (
    QUEUE_AI,
    QUEUE_DEFAULT,
    QUEUE_EXPORT,
    QUEUE_MEDIA,
    QUEUE_SCAN,
    QUEUE_SEARCH,
    TASK_ANALYZE_ASSET_AI,
    TASK_ANALYZE_SHOT_AI,
    TASK_ANALYZE_SHOTS,
    TASK_BACKFILL_SEARCH_DOCS,
    TASK_EXPORT_BUNDLE,
    TASK_EXPORT_SCRIPT_CSV,
    TASK_EXPORT_SHOT_CLIP,
    TASK_FINGERPRINT_JOB,
    TASK_GENERATE_ASSET_POSTER,
    TASK_LEGACY_IMPORT,
    TASK_REBUILD_ASSET_SEARCH_DOCS,
    TASK_REBUILD_SHOT_SEARCH_DOC,
    TASK_RESCAN_ASSET,
    TASK_SCAN_SOURCE_DIRECTORY,
    TASK_SWEEP_SEARCH_DOCS,
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


def enqueue_fingerprint_job(job_id: int) -> str:
    """入队指纹计算任务（PR-C；scan 队列顺序读，批量任务内部串行）。"""
    result = celery_client.send_task(
        TASK_FINGERPRINT_JOB, args=[job_id], queue=QUEUE_SCAN
    )
    return result.id


def enqueue_legacy_import(run_id: int) -> str:
    """入队历史证据导入任务（PR-C Gate B；只读 AssetLocation，零文件 IO）。"""
    result = celery_client.send_task(TASK_LEGACY_IMPORT, args=[run_id], queue=QUEUE_DEFAULT)
    return result.id


def enqueue_analyze_shots(run_id: int) -> str:
    """入队镜头分析任务（media 队列），返回 celery_task_id。"""
    result = celery_client.send_task(TASK_ANALYZE_SHOTS, args=[run_id], queue=QUEUE_MEDIA)
    return result.id


def enqueue_export_clip(export_id: int) -> str:
    """入队片段导出任务（media 队列），返回 celery_task_id。"""
    result = celery_client.send_task(TASK_EXPORT_SHOT_CLIP, args=[export_id], queue=QUEUE_MEDIA)
    return result.id


def enqueue_generate_poster(asset_id: int) -> str:
    """入队素材海报生成任务（media 队列），返回 celery_task_id。"""
    result = celery_client.send_task(
        TASK_GENERATE_ASSET_POSTER, args=[asset_id], queue=QUEUE_MEDIA
    )
    return result.id


def enqueue_analyze_asset_ai(run_id: int) -> str:
    """入队素材级 AI 分析任务（ai 队列），返回 celery_task_id。"""
    result = celery_client.send_task(TASK_ANALYZE_ASSET_AI, args=[run_id], queue=QUEUE_AI)
    return result.id


def enqueue_analyze_shot_ai(run_id: int, shot_id: int) -> str:
    """入队单镜头 AI 分析任务（ai 队列），返回 celery_task_id。"""
    result = celery_client.send_task(
        TASK_ANALYZE_SHOT_AI, args=[run_id, shot_id], queue=QUEUE_AI
    )
    return result.id


def enqueue_rebuild_shot_search_doc(shot_id: int, force_reembed: bool = False) -> str:
    """入队单镜头检索文档重建（search 队列），返回 celery_task_id。"""
    result = celery_client.send_task(
        TASK_REBUILD_SHOT_SEARCH_DOC, args=[shot_id, force_reembed], queue=QUEUE_SEARCH
    )
    return result.id


def enqueue_rebuild_asset_search_docs(asset_id: int, force_reembed: bool = False) -> str:
    """入队单素材检索文档重建（search 队列），返回 celery_task_id。"""
    result = celery_client.send_task(
        TASK_REBUILD_ASSET_SEARCH_DOCS, args=[asset_id, force_reembed], queue=QUEUE_SEARCH
    )
    return result.id


def enqueue_sweep_search_docs(limit: int = 500, force_reembed: bool = False) -> str:
    """入队检索文档兜底扫描（search 队列），返回 celery_task_id。"""
    result = celery_client.send_task(
        TASK_SWEEP_SEARCH_DOCS, args=[limit, force_reembed], queue=QUEUE_SEARCH
    )
    return result.id


def enqueue_backfill_search_docs(
    only_failed: bool = False, force_reembed: bool = False, limit: int = 1000
) -> str:
    """入队全量/失败回填（search 队列），返回 celery_task_id。危险操作需显式参数。"""
    result = celery_client.send_task(
        TASK_BACKFILL_SEARCH_DOCS, args=[only_failed, force_reembed, limit], queue=QUEUE_SEARCH
    )
    return result.id


def enqueue_export_script(export_id: int) -> str:
    """入队脚本剪辑清单导出（export 队列；worker 按 export_format 多格式输出）。"""
    result = celery_client.send_task(
        TASK_EXPORT_SCRIPT_CSV, args=[export_id], queue=QUEUE_EXPORT
    )
    return result.id


# 兼容旧名（CSV 专用语义；现统一走 enqueue_export_script）
enqueue_export_script_csv = enqueue_export_script


def enqueue_export_bundle(export_id: int) -> str:
    """入队多镜头 ZIP 打包导出（media 队列：裁剪各 clip → 打包），返回 celery_task_id。"""
    result = celery_client.send_task(
        TASK_EXPORT_BUNDLE, args=[export_id], queue=QUEUE_MEDIA
    )
    return result.id
