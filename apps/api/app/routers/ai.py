"""PR-03A AI 分析路由：发起/查询素材与镜头的真实 AI 状态 + provider 健康回显。

不在 API 进程调用 provider 网络（仅入队 + 读库 + 回显配置）。标签拆解/人工审核属 PR-03B。
"""

from __future__ import annotations

from clipmind_shared.models import Asset, Shot
from clipmind_shared.models.enums import AssetStatus, ShotStatus
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.schemas.ai import (
    AIAnalysisOut,
    AIProviderHealthOut,
    AnalyzeAIAcceptedOut,
    ShotAIOut,
    to_ai_analysis_out,
    to_shot_ai_out,
)
from app.services import ai_dispatch

router = APIRouter(tags=["ai"])


async def _start_asset_ai(asset_id: int, db: AsyncSession) -> AnalyzeAIAcceptedOut:
    asset = await db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="素材不存在")
    if asset.status == AssetStatus.SOURCE_MISSING:
        raise HTTPException(status_code=409, detail="源文件缺失，无法分析")
    if asset.media_kind == "image":
        # P2a：图片走图片理解链路（输入为海报副本；worker 层按 media_kind 分发）
        if not asset.poster_path:
            raise HTTPException(
                status_code=409, detail="图片海报尚未生成（扫描后自动生成），稍后再试或重新扫描"
            )
    else:
        ready_shots = await db.scalar(
            select(func.count(Shot.id)).where(
                Shot.asset_id == asset.id,
                Shot.status == ShotStatus.READY,
                Shot.retired_at.is_(None),
            )
        )
        if not ready_shots:
            raise HTTPException(status_code=409, detail="该素材还没有可用镜头，请先完成拆镜头")
    try:
        run = await ai_dispatch.request_ai_analysis(db, asset)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"无法入队 AI 分析: {exc}") from exc
    return AnalyzeAIAcceptedOut(
        asset_id=asset.id, run_id=run.id, status=run.status, celery_task_id=run.celery_task_id
    )


@router.post(
    "/assets/{asset_id}/analyze",
    response_model=AnalyzeAIAcceptedOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def analyze_asset(
    asset_id: int, db: AsyncSession = Depends(get_db)
) -> AnalyzeAIAcceptedOut:
    return await _start_asset_ai(asset_id, db)


@router.post(
    "/assets/{asset_id}/ai-analysis/retry",
    response_model=AnalyzeAIAcceptedOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_asset_ai(
    asset_id: int, db: AsyncSession = Depends(get_db)
) -> AnalyzeAIAcceptedOut:
    return await _start_asset_ai(asset_id, db)


@router.get("/assets/{asset_id}/ai-analysis", response_model=AIAnalysisOut)
async def get_asset_ai_analysis(
    asset_id: int, response: Response, db: AsyncSession = Depends(get_db)
) -> AIAnalysisOut:
    asset = await db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="素材不存在")
    response.headers["Cache-Control"] = "no-store"  # 任务状态接口不缓存
    run = await ai_dispatch.get_latest_ai_run(db, asset_id)
    completed = await ai_dispatch.count_completed_analyses(db, asset_id)
    return to_ai_analysis_out(asset_id, run, completed)


@router.post(
    "/shots/{shot_id}/analyze",
    response_model=AnalyzeAIAcceptedOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def analyze_shot(
    shot_id: int, db: AsyncSession = Depends(get_db)
) -> AnalyzeAIAcceptedOut:
    shot = await db.get(Shot, shot_id)
    if shot is None:
        raise HTTPException(status_code=404, detail="镜头不存在")
    asset = await db.get(Asset, shot.asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="素材不存在")
    try:
        run = await ai_dispatch.request_ai_analysis(db, asset, only_shot_id=shot_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"无法入队 AI 分析: {exc}") from exc
    return AnalyzeAIAcceptedOut(
        asset_id=asset.id, run_id=run.id, status=run.status, celery_task_id=run.celery_task_id
    )


@router.get("/shots/{shot_id}/ai", response_model=ShotAIOut)
async def get_shot_ai(
    shot_id: int, db: AsyncSession = Depends(get_db)
) -> ShotAIOut:
    shot = await db.get(Shot, shot_id)
    if shot is None:
        raise HTTPException(status_code=404, detail="镜头不存在")
    row = await ai_dispatch.get_shot_analysis(db, shot_id)
    return to_shot_ai_out(shot_id, row)


@router.get("/ai/provider/health", response_model=AIProviderHealthOut)
async def ai_provider_health() -> AIProviderHealthOut:
    s = get_settings()
    provider = (s.ai_provider or "").strip().lower()
    if provider == "fake":
        return AIProviderHealthOut(
            provider="fake", configured=True, supports_images=True,
            max_images=s.ai_max_images, detail="FakeProvider（确定性，测试/CI）",
        )
    if provider == "mimo":
        configured = bool(s.ai_base_url and s.ai_api_key)
        return AIProviderHealthOut(
            provider="mimo",
            configured=configured,
            supports_images=None,  # 真实能力需运行 scripts/probe_ai_provider.py 探测
            max_images=s.ai_max_images,
            detail="已配置" if configured else "缺少 AI_BASE_URL / AI_API_KEY",
        )
    return AIProviderHealthOut(
        provider=provider or "notconfigured",
        configured=False,
        detail="未配置 AI_PROVIDER（fake | mimo）",
    )
