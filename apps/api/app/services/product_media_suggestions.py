"""PM：确定性产品候选（文件名/目录/别名/已有 AI 文本命中）。

只产出候选，绝不写正式关系；人工确认后由前端调 create_link 落库
（origin=path_or_filename_confirmed / text_suggestion_confirmed）。
匹配全部大小写不敏感；候选按（匹配类型优先级, family_id）确定性排序。
"""

from __future__ import annotations

from clipmind_shared.models import (
    AIShotAnalysis,
    Asset,
    ProductCatalogAlias,
    ProductFamily,
    Shot,
)
from clipmind_shared.models.enums import CatalogStatus
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_TYPE_PRIORITY = {"path": 0, "filename": 1, "alias": 1, "ai_text": 2}


def _norm(s: str) -> str:
    return (s or "").strip().lower()


async def _candidate_terms(db: AsyncSession) -> list[dict]:
    """可匹配词表：family 名称/code + family/variant 层 alias（排除 merged/archived）。"""
    fams = (
        await db.execute(
            select(ProductFamily).where(
                ProductFamily.status.notin_(
                    [CatalogStatus.MERGED, CatalogStatus.ARCHIVED]
                ),
                ProductFamily.merged_into_id.is_(None),
            )
        )
    ).scalars()
    terms: list[dict] = []
    fam_by_id: dict[int, ProductFamily] = {}
    for f in fams:
        fam_by_id[f.id] = f
        for term in (f.name_zh, f.name_en, f.code):
            t = _norm(term or "")
            if len(t) >= 2:
                terms.append({"term": t, "family_id": f.id, "source": "name",
                              "display": term})
    aliases = (
        await db.execute(
            select(ProductCatalogAlias).where(
                ProductCatalogAlias.family_id.in_(list(fam_by_id) or [0])
            )
        )
    ).scalars()
    for a in aliases:
        t = _norm(a.alias)
        if a.family_id in fam_by_id and len(t) >= 2:
            terms.append({"term": t, "family_id": a.family_id, "source": "alias",
                          "display": a.alias})
    return terms


async def suggest_for_target(
    db: AsyncSession, *, target_type: str, target_id: int
) -> list[dict]:
    """对 Asset/Shot 产出确定性候选（path/filename/alias/ai_text）。"""
    if target_type == "asset":
        asset = (
            await db.execute(select(Asset).where(Asset.id == target_id))
        ).scalar_one_or_none()
        if asset is None:
            raise HTTPException(status_code=404, detail="素材不存在")
        shot_ids: list[int] = []
    elif target_type == "shot":
        shot = (
            await db.execute(select(Shot).where(Shot.id == target_id))
        ).scalar_one_or_none()
        if shot is None:
            raise HTTPException(status_code=404, detail="镜头不存在")
        asset = (
            await db.execute(select(Asset).where(Asset.id == shot.asset_id))
        ).scalar_one()
        shot_ids = [shot.id]
    else:
        raise HTTPException(status_code=422, detail=f"未知目标类型: {target_type}")

    rel = _norm(asset.relative_path)
    dir_part = _norm("/".join(rel.replace("\\", "/").split("/")[:-1]))
    file_part = _norm(asset.filename)

    # 已有 AI 分析文本（该 asset 全部镜头的解析文本；只读命中，不新调 AI）
    ai_texts: list[str] = []
    ai_rows = (
        await db.execute(
            select(AIShotAnalysis.parsed_result).join(
                Shot, Shot.id == AIShotAnalysis.shot_id
            ).where(
                Shot.asset_id == asset.id,
                *( [Shot.id.in_(shot_ids)] if shot_ids else [] ),
            )
        )
    ).scalars()
    for parsed in ai_rows:
        if isinstance(parsed, dict):
            ai_texts.append(_norm(str(parsed)))

    out: dict[tuple[int, str], dict] = {}
    for entry in await _candidate_terms(db):
        term = entry["term"]
        hit_type: str | None = None
        matched_in = ""
        if term in dir_part:
            hit_type, matched_in = "path", "目录名"
        elif term in file_part:
            hit_type, matched_in = "filename", "文件名"
        elif any(term in t for t in ai_texts):
            hit_type, matched_in = "ai_text", "AI 分析文本"
        if hit_type is None:
            continue
        if entry["source"] == "alias" and hit_type in ("path", "filename"):
            hit_type = "alias" if hit_type == "filename" else "path"
        key = (entry["family_id"], hit_type)
        if key not in out:
            out[key] = {
                "family_id": entry["family_id"],
                "suggestion_type": hit_type,
                "matched_text": entry["display"],
                "matched_in": matched_in,
                "origin_on_confirm": (
                    "text_suggestion_confirmed"
                    if hit_type == "ai_text"
                    else "path_or_filename_confirmed"
                ),
            }
    ordered = sorted(
        out.values(),
        key=lambda s: (_TYPE_PRIORITY.get(s["suggestion_type"], 9), s["family_id"]),
    )
    # 附 family 名称（展示用）
    if ordered:
        fams = {
            f.id: f
            for f in (
                await db.execute(
                    select(ProductFamily).where(
                        ProductFamily.id.in_({s["family_id"] for s in ordered})
                    )
                )
            ).scalars()
        }
        for s in ordered:
            fam = fams.get(s["family_id"])
            s["family_name"] = fam.name_zh if fam else ""
            s["family_code"] = fam.code if fam else ""
    return ordered
