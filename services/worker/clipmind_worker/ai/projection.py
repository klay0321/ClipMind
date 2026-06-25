"""AI 标签检索投影（PR-03B.1）。

AI 分析成功后把结构化结果投影为 active AI ShotTag（供 projection-first 列表筛选）。
每个 shot 是某代次的具体行（shot_id 即绑定 generation），故无需额外 generation 列：
重新分析同一 shot → 旧 active AI 投影置 inactive 再写新；新代次是新 shot 行，旧投影随旧 shot
级联删除。AI 与 human 投影各存历史（source 区分），互不覆盖。
"""

from __future__ import annotations

from typing import Any

from clipmind_shared.db.base import utcnow
from clipmind_shared.models import ShotTag, Tag
from clipmind_shared.models.enums import TagSource
from clipmind_shared.review import normalize_name, projected_tags
from sqlalchemy import select, update
from sqlalchemy.orm import Session


def _get_or_create_tag(session: Session, tag_type: str, tag_name: str) -> Tag:
    norm = normalize_name(tag_name)
    tag = session.execute(
        select(Tag).where(Tag.tag_type == tag_type, Tag.normalized_name == norm)
    ).scalars().first()
    if tag is None:
        tag = Tag(tag_type=tag_type, tag_name=tag_name, normalized_name=norm)
        session.add(tag)
        session.flush()
    return tag


def project_ai_tags(
    session: Session,
    *,
    shot_id: int,
    parsed: dict[str, Any] | None,
    ai_analysis_id: int | None,
    confidence: float | None,
) -> int:
    """把 AI 结构化结果投影为 active AI ShotTag。返回写入的标签数。"""
    # 旧 active AI 投影置 inactive（保留历史）
    session.execute(
        update(ShotTag)
        .where(
            ShotTag.shot_id == shot_id,
            ShotTag.source == TagSource.AI,
            ShotTag.active.is_(True),
        )
        .values(active=False, updated_at=utcnow())
    )
    session.flush()
    n = 0
    for tag_type, tag_name in projected_tags(parsed):
        tag = _get_or_create_tag(session, tag_type, tag_name)
        session.add(
            ShotTag(
                shot_id=shot_id, tag_id=tag.id, source=TagSource.AI,
                source_ai_analysis_id=ai_analysis_id, confidence=confidence, active=True,
            )
        )
        n += 1
    session.flush()
    return n


def project_human_tags(
    session: Session,
    *,
    shot_id: int,
    confirmed_result: dict[str, Any] | None,
    reviewer_label: str | None,
    source_ai_analysis_id: int | None,
) -> int:
    """把人工确认结果投影为 active human ShotTag（同步，供回填复用）。"""
    session.execute(
        update(ShotTag)
        .where(
            ShotTag.shot_id == shot_id,
            ShotTag.source == TagSource.HUMAN,
            ShotTag.active.is_(True),
        )
        .values(active=False, updated_at=utcnow())
    )
    session.flush()
    n = 0
    for tag_type, tag_name in projected_tags(confirmed_result):
        tag = _get_or_create_tag(session, tag_type, tag_name)
        session.add(
            ShotTag(
                shot_id=shot_id, tag_id=tag.id, source=TagSource.HUMAN,
                source_ai_analysis_id=source_ai_analysis_id,
                confirmed_by=reviewer_label, confirmed_at=utcnow(), active=True,
            )
        )
        n += 1
    session.flush()
    return n
