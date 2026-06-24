"""Shot / 镜头分析相关 schema。

注意：绝不暴露服务器派生文件绝对路径；前端按 shot_id 拼接资源 URL
（/api/shots/{id}/thumbnail|keyframe|preview）。本 PR 不含任何 AI 字段。
"""

from __future__ import annotations

from datetime import datetime

from clipmind_shared.models import Asset, MediaProcessingRun, Shot
from clipmind_shared.models.enums import MediaRunStatus, ShotStatus
from pydantic import BaseModel


class ShotOut(BaseModel):
    id: int
    asset_id: int
    asset_filename: str | None = None
    sequence_no: int
    start_time: float
    end_time: float
    duration: float
    detector_type: str
    detector_confidence: float | None
    status: ShotStatus
    error_message: str | None
    has_keyframe: bool
    has_thumbnail: bool
    has_proxy: bool
    keyframe_count: int = 0  # 关键帧条可用帧数（0 表示仅主关键帧）
    created_at: datetime
    updated_at: datetime


class ShotDetailOut(ShotOut):
    # 来源素材信息（用于镜头详情展示，非 AI）
    asset_filename: str
    asset_duration: float | None
    asset_width: int | None
    asset_height: int | None
    asset_video_codec: str | None
    asset_audio_codec: str | None


class ShotAnalysisOut(BaseModel):
    """素材最近一次镜头分析运行的状态（轮询用）。"""

    asset_id: int
    has_run: bool
    run_id: int | None = None
    status: MediaRunStatus | None = None
    progress: int = 0
    current_step: str | None = None
    total_shots: int = 0
    completed_shots: int = 0
    error_message: str | None = None
    celery_task_id: str | None = None
    generation: int = 0
    queued_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    shot_count: int = 0


class AnalyzeAcceptedOut(BaseModel):
    asset_id: int
    run_id: int
    status: MediaRunStatus
    celery_task_id: str | None = None
    detail: str = "已入队镜头分析"


def to_shot_out(shot: Shot, asset_filename: str | None = None) -> ShotOut:
    return ShotOut(
        id=shot.id,
        asset_id=shot.asset_id,
        asset_filename=asset_filename,
        sequence_no=shot.sequence_no,
        start_time=shot.start_time,
        end_time=shot.end_time,
        duration=shot.duration,
        detector_type=shot.detector_type,
        detector_confidence=shot.detector_confidence,
        status=shot.status,
        error_message=shot.error_message,
        has_keyframe=bool(shot.keyframe_path),
        has_thumbnail=bool(shot.thumbnail_path),
        has_proxy=bool(shot.proxy_path),
        keyframe_count=len(shot.keyframe_paths or []),
        created_at=shot.created_at,
        updated_at=shot.updated_at,
    )


def to_shot_detail(shot: Shot, asset: Asset) -> ShotDetailOut:
    base = to_shot_out(shot, asset.filename).model_dump()
    return ShotDetailOut(
        **base,
        asset_duration=asset.duration,
        asset_width=asset.width,
        asset_height=asset.height,
        asset_video_codec=asset.video_codec,
        asset_audio_codec=asset.audio_codec,
    )


def to_analysis_out(
    asset_id: int, run: MediaProcessingRun | None, shot_count: int
) -> ShotAnalysisOut:
    if run is None:
        return ShotAnalysisOut(asset_id=asset_id, has_run=False, shot_count=shot_count)
    return ShotAnalysisOut(
        asset_id=asset_id,
        has_run=True,
        run_id=run.id,
        status=run.status,
        progress=run.progress,
        current_step=run.current_step,
        total_shots=run.total_shots,
        completed_shots=run.completed_shots,
        error_message=run.error_message,
        celery_task_id=run.celery_task_id,
        generation=run.generation,
        queued_at=run.queued_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        shot_count=shot_count,
    )
