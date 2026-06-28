"""PR-06B 收藏业务逻辑：四类收藏 CRUD + 去重 + 安全 context。

- asset 类型关联 asset_id；shot/search_result/script_match_result 关联底层 shot_id。
- context 仅存安全来源快照（分数/query 摘要/segment 信息），有字节上限，剔除路径类字段。
- 去重：同一 (target_type, 实体) 已收藏则幂等返回。删除只删 favorite，不删 Asset/Shot。
"""

from __future__ import annotations

import json

from clipmind_shared.models import Asset, Favorite, Shot
from clipmind_shared.models.enums import (
    FavoriteTargetType,
)
from clipmind_shared.models.favorite import FAVORITE_CONTEXT_MAX_BYTES
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.favorite import AssetMini, FavoriteCreate, FavoriteOut
from app.schemas.shot import to_shot_out

# context 中禁止出现的疑似路径/敏感键（防止把本机路径/凭据塞进收藏）
_FORBIDDEN_CONTEXT_KEYS = {"path", "source_path", "abs_path", "api_key", "key", "endpoint", "token"}


def _sanitize_context(context: dict | None) -> dict | None:
    if context is None:
        return None
    if not isinstance(context, dict):
        raise HTTPException(status_code=422, detail="context 必须是对象")
    lowered = {str(k).lower() for k in context}
    if lowered & _FORBIDDEN_CONTEXT_KEYS:
        raise HTTPException(status_code=422, detail="context 不得包含路径/凭据类字段")
    if len(json.dumps(context, ensure_ascii=False).encode("utf-8")) > FAVORITE_CONTEXT_MAX_BYTES:
        raise HTTPException(status_code=422, detail="context 过大")
    return context


async def create(db: AsyncSession, req: FavoriteCreate) -> Favorite:
    is_asset = req.target_type == FavoriteTargetType.ASSET
    if is_asset:
        if req.asset_id is None or req.shot_id is not None:
            raise HTTPException(status_code=422, detail="素材收藏必须且只能提供 asset_id")
        if await db.get(Asset, req.asset_id) is None:
            raise HTTPException(status_code=404, detail="素材不存在")
    else:
        if req.shot_id is None or req.asset_id is not None:
            raise HTTPException(status_code=422, detail="该类型收藏必须且只能提供 shot_id")
        if await db.get(Shot, req.shot_id) is None:
            raise HTTPException(status_code=404, detail="镜头不存在")

    context = _sanitize_context(req.context)

    # 去重：同一 (target_type, 实体) 已存在则幂等返回
    dedupe = select(Favorite).where(Favorite.target_type == req.target_type)
    dedupe = dedupe.where(
        Favorite.asset_id == req.asset_id if is_asset else Favorite.shot_id == req.shot_id
    )
    existing = (await db.scalars(dedupe)).first()
    if existing is not None:
        return existing

    fav = Favorite(
        target_type=req.target_type,
        asset_id=req.asset_id if is_asset else None,
        shot_id=None if is_asset else req.shot_id,
        context=context,
    )
    db.add(fav)
    await db.commit()
    await db.refresh(fav)
    return fav


async def list_favorites(
    db: AsyncSession, *, page: int, page_size: int, target_type: FavoriteTargetType | None
) -> tuple[list[FavoriteOut], int]:
    base = select(Favorite)
    count = select(func.count(Favorite.id))
    if target_type is not None:
        base = base.where(Favorite.target_type == target_type)
        count = count.where(Favorite.target_type == target_type)
    total = int(await db.scalar(count) or 0)
    favs = (
        await db.scalars(
            base.order_by(Favorite.created_at.desc(), Favorite.id.desc())
            .offset((page - 1) * page_size).limit(page_size)
        )
    ).all()
    if not favs:
        return [], total

    shot_ids = [f.shot_id for f in favs if f.shot_id is not None]
    asset_ids = [f.asset_id for f in favs if f.asset_id is not None]
    shots: dict[int, object] = {}
    if shot_ids:
        loaded = (await db.scalars(select(Shot).where(Shot.id.in_(shot_ids)))).all()
        shots = {s.id: s for s in loaded}
    all_asset_ids = set(asset_ids) | {s.asset_id for s in shots.values()}
    assets: dict[int, object] = {}
    if all_asset_ids:
        assets = {
            a.id: a
            for a in (await db.scalars(select(Asset).where(Asset.id.in_(all_asset_ids)))).all()
        }

    items: list[FavoriteOut] = []
    for f in favs:
        shot_out = None
        asset_out = None
        if f.shot_id is not None and f.shot_id in shots:
            sh = shots[f.shot_id]
            af = assets.get(sh.asset_id)
            shot_out = to_shot_out(sh, af.filename if af else None)
        if f.asset_id is not None and f.asset_id in assets:
            a = assets[f.asset_id]
            asset_out = AssetMini(
                id=a.id, filename=a.filename, duration=a.duration, width=a.width, height=a.height
            )
        items.append(
            FavoriteOut(
                id=f.id, target_type=f.target_type, asset_id=f.asset_id, shot_id=f.shot_id,
                context=f.context, created_at=f.created_at, shot=shot_out, asset=asset_out,
            )
        )
    return items, total


async def delete(db: AsyncSession, favorite_id: int) -> None:
    fav = await db.get(Favorite, favorite_id)
    if fav is None:
        raise HTTPException(status_code=404, detail="收藏不存在")
    await db.delete(fav)
    await db.commit()
