"""AI 镜头分析编排核心（PR-03A）。

无 Celery / 无锁的纯逻辑，便于直接单测（任务包装层负责加锁/异常）：
- 解析镜头关键帧（多帧）为绝对路径并计算内容指纹；
- 缓存去重：相同输入命中已 completed 的分析则跳过、不重复计费；
- 调用 provider，超时/限流/坏响应按 AI_RETRIES 指数退避重试；鉴权/未配置为致命错误不重试；
- 能力不足（无图）降级：标 degraded、parsed=None，**绝不伪造视觉结果**；
- 每次调用落 ai_call_log（脱敏，无密钥）；每镜头 upsert ai_shot_analysis；
- run 状态机：completed / partial / failed。
"""

from __future__ import annotations

import logging
import os
import time
from time import perf_counter
from typing import Any

from clipmind_shared.ai import (
    FrameRef,
    ProviderAuthError,
    ProviderBadResponse,
    ProviderError,
    ProviderNotConfigured,
    build_analysis_prompt,
    compute_fingerprint,
    get_provider,
    hash_file,
    shot_analysis_json_schema,
    validate_shot_analysis,
)
from clipmind_shared.ai.providers.base import AnalyzeOutcome, Usage, VisualAnalysisProvider
from clipmind_shared.constants import AI_SCHEMA_VERSION, ERROR_MESSAGE_MAX_LEN
from clipmind_shared.db.base import utcnow
from clipmind_shared.models import (
    AIAnalysisRun,
    AICallLog,
    AIShotAnalysis,
    Asset,
    Shot,
)
from clipmind_shared.models.enums import (
    AICallStatus,
    AIRunStatus,
    AIShotAnalysisStatus,
    AssetStatus,
    ShotStatus,
)
from clipmind_shared.security import PathSecurityError, safe_join_within_root
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from clipmind_worker.ai.projection import project_ai_tags
from clipmind_worker.config import WorkerSettings
from clipmind_worker.media import storage

logger = logging.getLogger(__name__)

ANALYZE_METHOD = "analyze_frames"


def build_provider(settings: WorkerSettings) -> VisualAnalysisProvider:
    return get_provider(
        settings.ai_provider,
        base_url=settings.ai_base_url or None,
        api_key=settings.ai_api_key or None,
        model=settings.ai_model or None,
        timeout=settings.ai_timeout,
        max_images=settings.ai_max_images,
        api_key_header=settings.ai_api_key_header,
        max_completion_tokens=settings.ai_max_completion_tokens,
    )


def _shot_relpaths(shot: Shot) -> list[str]:
    if shot.keyframe_paths:
        return list(shot.keyframe_paths)
    if shot.keyframe_path:
        return [shot.keyframe_path]
    return []


def _resolve_frames(root_real: str, shot: Shot, max_images: int) -> list[FrameRef]:
    refs: list[FrameRef] = []
    for rel in _shot_relpaths(shot)[: max(max_images, 0)]:
        parts = [p for p in rel.split("/") if p]
        try:
            abspath = safe_join_within_root(root_real, *parts)
        except PathSecurityError:
            logger.warning("跳过越界关键帧路径: %s", rel)
            continue
        if os.path.isfile(abspath):
            refs.append(FrameRef(path=abspath, sha256=hash_file(abspath)))
    return refs


def _estimate_cost(settings: WorkerSettings, usage: Usage | None) -> float | None:
    if usage is None:
        return None
    if settings.ai_price_input_per_1k <= 0 and settings.ai_price_output_per_1k <= 0:
        return None
    inp = (usage.input_tokens or 0) / 1000 * settings.ai_price_input_per_1k
    out = (usage.output_tokens or 0) / 1000 * settings.ai_price_output_per_1k
    return round(inp + out, 6)


def _log_call(
    session: Session,
    *,
    run: AIAnalysisRun,
    shot: Shot,
    provider_name: str,
    model: str | None,
    attempt: int,
    status: AICallStatus,
    usage: Usage | None = None,
    est_cost: float | None = None,
    duration_ms: int | None = None,
    http_status: int | None = None,
    error_code: str | None = None,
) -> None:
    session.add(
        AICallLog(
            run_id=run.id,
            shot_id=shot.id,
            asset_id=shot.asset_id,
            provider=provider_name,
            model=model,
            method=ANALYZE_METHOD,
            attempt_no=attempt,
            input_images=usage.input_images if usage else 0,
            input_tokens=usage.input_tokens if usage else None,
            output_tokens=usage.output_tokens if usage else None,
            est_cost=est_cost,
            duration_ms=duration_ms,
            status=status,
            http_status=http_status,
            error_code=error_code,
        )
    )


def _upsert_shot_analysis(
    session: Session,
    shot: Shot,
    run: AIAnalysisRun,
    *,
    status: AIShotAnalysisStatus,
    provider_name: str,
    model: str | None,
    prompt_version: str,
    fingerprint: str | None,
    parsed: dict[str, Any] | None,
    raw_excerpt: str | None,
    confidence: float | None,
    input_summary: dict[str, Any] | None,
    degraded_reason: str | None,
    duration_ms: int | None,
) -> AIShotAnalysis:
    row = session.execute(
        select(AIShotAnalysis).where(AIShotAnalysis.shot_id == shot.id)
    ).scalar_one_or_none()
    if row is None:
        row = AIShotAnalysis(shot_id=shot.id, asset_id=shot.asset_id)
        session.add(row)
    row.run_id = run.id
    row.asset_id = shot.asset_id
    row.provider = provider_name
    row.model = model
    row.prompt_version = prompt_version
    row.schema_version = AI_SCHEMA_VERSION
    row.input_fingerprint = fingerprint
    row.input_summary = input_summary
    row.parsed_result = parsed
    row.raw_response_excerpt = raw_excerpt
    row.confidence = confidence
    row.status = status
    row.degraded_reason = degraded_reason
    row.duration_ms = duration_ms
    return row


def _backoff(attempt: int, retry_after: float | None) -> float:
    return min(2 ** (attempt - 1), 8) + (retry_after or 0)


def analyze_shot(
    session: Session,
    provider: VisualAnalysisProvider,
    settings: WorkerSettings,
    run: AIAnalysisRun,
    shot: Shot,
    *,
    root_real: str,
    prompt: str,
    schema: dict[str, Any],
    images_ok: bool,
    provider_name: str,
    model: str | None,
    sleep=time.sleep,
) -> str:
    """分析单个镜头，返回 completed|skipped|degraded|failed。鉴权/未配置抛出（致命）。"""
    frames = _resolve_frames(root_real, shot, settings.ai_max_images)
    fingerprint = compute_fingerprint(
        frame_hashes=[f.sha256 or "" for f in frames],
        provider=provider_name,
        model=model or "",
        prompt_version=settings.ai_prompt_version,
        schema_version=AI_SCHEMA_VERSION,
        params={"max_images": settings.ai_max_images},
    )
    input_summary = {"frames": len(frames)}

    existing = session.execute(
        select(AIShotAnalysis).where(AIShotAnalysis.shot_id == shot.id)
    ).scalar_one_or_none()
    if (
        existing is not None
        and existing.status == AIShotAnalysisStatus.COMPLETED
        and existing.input_fingerprint == fingerprint
    ):
        existing.run_id = run.id  # 关联本次运行，但不重复计费
        return "skipped"

    # 能力不足（无图）：降级，不调用、不伪造
    if not images_ok:
        run.degraded = True
        _upsert_shot_analysis(
            session, shot, run,
            status=AIShotAnalysisStatus.DEGRADED,
            provider_name=provider_name, model=model,
            prompt_version=settings.ai_prompt_version,
            fingerprint=fingerprint, parsed=None, raw_excerpt=None,
            confidence=None, input_summary=input_summary,
            degraded_reason="provider_no_image_support", duration_ms=None,
        )
        _log_call(
            session, run=run, shot=shot, provider_name=provider_name, model=model,
            attempt=1, status=AICallStatus.DEGRADED, usage=Usage(input_images=0),
        )
        return "degraded"

    attempt = 0
    last_exc: ProviderError | None = None
    outcome: AnalyzeOutcome | None = None
    t0 = perf_counter()
    while attempt <= settings.ai_retries:
        attempt += 1
        try:
            cand = provider.analyze_frames(
                frames, prompt=prompt, schema=schema, timeout=settings.ai_timeout
            )
            if cand.degraded:
                run.degraded = True
                _log_call(
                    session, run=run, shot=shot, provider_name=provider_name, model=model,
                    attempt=attempt, status=AICallStatus.DEGRADED, usage=cand.usage,
                    http_status=cand.http_status,
                )
                _upsert_shot_analysis(
                    session, shot, run,
                    status=AIShotAnalysisStatus.DEGRADED,
                    provider_name=provider_name, model=cand.model,
                    prompt_version=settings.ai_prompt_version,
                    fingerprint=fingerprint, parsed=None, raw_excerpt=None,
                    confidence=None, input_summary=input_summary,
                    degraded_reason=cand.degraded_reason, duration_ms=None,
                )
                return "degraded"
            validate_shot_analysis(cand.parsed or {})
            outcome = cand
            break
        except (ProviderAuthError, ProviderNotConfigured) as exc:
            _log_call(
                session, run=run, shot=shot, provider_name=provider_name, model=model,
                attempt=attempt, status=AICallStatus.FAILED,
                http_status=exc.http_status, error_code=exc.error_code,
            )
            raise  # 致命：整个 run 失败
        except ValidationError:
            last_exc = ProviderBadResponse("schema_invalid")
            _log_call(
                session, run=run, shot=shot, provider_name=provider_name, model=model,
                attempt=attempt, status=AICallStatus.FAILED, error_code="schema_invalid",
            )
        except ProviderError as exc:
            last_exc = exc
            _log_call(
                session, run=run, shot=shot, provider_name=provider_name, model=model,
                attempt=attempt, status=_call_status_for(exc),
                http_status=exc.http_status, error_code=exc.error_code,
            )
        if attempt <= settings.ai_retries:
            sleep(_backoff(attempt, getattr(last_exc, "retry_after", None)))

    if outcome is None:
        _upsert_shot_analysis(
            session, shot, run,
            status=AIShotAnalysisStatus.FAILED,
            provider_name=provider_name, model=model,
            prompt_version=settings.ai_prompt_version,
            fingerprint=fingerprint, parsed=None, raw_excerpt=None,
            confidence=None, input_summary=input_summary,
            degraded_reason=(last_exc.error_code if last_exc else "unknown"), duration_ms=None,
        )
        run.failed_shots += 1
        return "failed"

    duration_ms = int((perf_counter() - t0) * 1000)
    est_cost = _estimate_cost(settings, outcome.usage)
    _log_call(
        session, run=run, shot=shot, provider_name=provider_name, model=outcome.model,
        attempt=attempt, status=AICallStatus.SUCCESS, usage=outcome.usage,
        est_cost=est_cost, duration_ms=duration_ms, http_status=outcome.http_status,
    )
    parsed = outcome.parsed or {}
    ai_row = _upsert_shot_analysis(
        session, shot, run,
        status=AIShotAnalysisStatus.COMPLETED,
        provider_name=provider_name, model=outcome.model,
        prompt_version=settings.ai_prompt_version,
        fingerprint=fingerprint, parsed=parsed, raw_excerpt=outcome.raw_excerpt,
        confidence=parsed.get("confidence"), input_summary=input_summary,
        degraded_reason=None, duration_ms=duration_ms,
    )
    session.flush()
    # 标签投影（projection-first 筛选的事实来源之一）；失败不静默、不丢 AI 结果，可由回填修复
    try:
        project_ai_tags(
            session, shot_id=shot.id, parsed=parsed,
            ai_analysis_id=ai_row.id, confidence=parsed.get("confidence"),
        )
        ai_row.projection_status = "ok"
    except Exception as exc:  # noqa: BLE001
        logger.error("AI 标签投影失败 shot=%s: %s", shot.id, exc)
        ai_row.projection_status = "error"
    run.analyzed_shots += 1
    return "completed"


def _call_status_for(exc: ProviderError) -> AICallStatus:
    code = getattr(exc, "error_code", "")
    if code == "timeout":
        return AICallStatus.TIMEOUT
    if code == "rate_limited":
        return AICallStatus.RATE_LIMITED
    return AICallStatus.FAILED


def run_asset_analysis(
    session: Session,
    run: AIAnalysisRun,
    asset: Asset,
    settings: WorkerSettings,
    *,
    provider: VisualAnalysisProvider | None = None,
    only_shot_id: int | None = None,
    sleep=time.sleep,
) -> dict[str, Any]:
    provider = provider or build_provider(settings)
    provider_name = getattr(provider, "name", settings.ai_provider or "notconfigured")
    caps = provider.capabilities()
    schema = shot_analysis_json_schema()
    prompt = build_analysis_prompt(schema)
    model = settings.ai_model or getattr(provider, "_model", None) or None

    run.status = AIRunStatus.RUNNING
    run.started_at = utcnow()
    run.heartbeat_at = utcnow()
    run.provider = provider_name
    run.model = model
    run.prompt_version = settings.ai_prompt_version
    run.schema_version = AI_SCHEMA_VERSION
    run.capabilities_snapshot = caps.model_dump()
    run.degraded = False
    asset.status = AssetStatus.AI_ANALYZING
    session.commit()

    stmt = (
        select(Shot)
        .where(
            Shot.asset_id == asset.id,
            Shot.status == ShotStatus.READY,
            Shot.retired_at.is_(None),
        )
        .order_by(Shot.generation.desc(), Shot.sequence_no.asc())
    )
    shots = list(session.execute(stmt).scalars().all())
    if only_shot_id is not None:
        shots = [s for s in shots if s.id == only_shot_id]

    # 空镜头必须失败：否则 run 假成功且把未拆镜头素材状态污染为 SHOT_SPLIT
    if not shots:
        run.total_shots = 0
        run.analyzed_shots = 0
        run.failed_shots = 0
        run.skipped_cached = 0
        run.status = AIRunStatus.FAILED
        run.error_message = "没有可分析的镜头（请先完成拆镜头）"
        run.finished_at = utcnow()
        run.heartbeat_at = utcnow()
        # 恢复素材状态（函数开头已置 AI_ANALYZING）：有可用镜头回 SHOT_SPLIT，否则回 INDEXED
        any_ready = session.execute(
            select(Shot.id)
            .where(
                Shot.asset_id == asset.id,
                Shot.status == ShotStatus.READY,
                Shot.retired_at.is_(None),
            )
            .limit(1)
        ).first()
        asset.status = AssetStatus.SHOT_SPLIT if any_ready else AssetStatus.INDEXED
        session.commit()
        return {
            "run_id": run.id,
            "asset_id": asset.id,
            "status": run.status.value,
            "total_shots": 0,
            "analyzed": 0,
            "failed": 0,
            "skipped_cached": 0,
            "degraded": run.degraded,
        }

    run.total_shots = len(shots)
    run.analyzed_shots = 0
    run.failed_shots = 0
    run.skipped_cached = 0
    session.commit()

    root_real = storage.data_root(settings.data_dir)
    images_ok = caps.supports_images
    fatal: ProviderError | None = None

    for i, shot in enumerate(shots, start=1):
        try:
            res = analyze_shot(
                session, provider, settings, run, shot,
                root_real=root_real, prompt=prompt, schema=schema,
                images_ok=images_ok, provider_name=provider_name, model=model, sleep=sleep,
            )
            if res == "skipped":
                run.skipped_cached += 1
        except (ProviderAuthError, ProviderNotConfigured) as exc:
            fatal = exc
            session.commit()
            break
        run.progress = int(i / max(len(shots), 1) * 100)
        run.heartbeat_at = utcnow()
        session.commit()

    if fatal is not None:
        run.status = AIRunStatus.FAILED
        run.error_message = f"{fatal.error_code}: {fatal}"[:ERROR_MESSAGE_MAX_LEN]
    elif run.failed_shots == 0:
        run.status = AIRunStatus.COMPLETED
        run.progress = 100
    elif run.analyzed_shots == 0 and run.skipped_cached == 0:
        run.status = AIRunStatus.FAILED
    else:
        run.status = AIRunStatus.PARTIAL
        run.progress = 100

    run.finished_at = utcnow()
    run.heartbeat_at = utcnow()
    asset.status = AssetStatus.SHOT_SPLIT
    session.commit()

    return {
        "run_id": run.id,
        "asset_id": asset.id,
        "status": run.status.value,
        "total_shots": run.total_shots,
        "analyzed": run.analyzed_shots,
        "failed": run.failed_shots,
        "skipped_cached": run.skipped_cached,
        "degraded": run.degraded,
    }
