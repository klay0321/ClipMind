"""从结构化结果（ShotAnalysisResult dict）派生检索标签投影。

把"有效结果"中的产品/场景/动作/镜头类型/营销/质量/风险投影为 (tag_type, tag_name) 列表，
供 shot_tag 同步（人工修改审核时在同一事务刷新投影）。
"""

from __future__ import annotations

from typing import Any

from clipmind_shared.models.enums import TagType


def projected_tags(result: dict[str, Any] | None) -> list[tuple[str, str]]:
    if not result:
        return []
    out: list[tuple[str, str]] = []

    def add(tag_type: TagType, name: Any) -> None:
        if isinstance(name, str) and name.strip():
            out.append((tag_type.value, name.strip()))

    product = result.get("product") or {}
    if isinstance(product, dict):
        add(TagType.PRODUCT, product.get("name"))
    add(TagType.SCENE, result.get("scene"))
    add(TagType.ACTION, result.get("action"))
    add(TagType.SHOT_TYPE, result.get("shot_type"))
    for m in result.get("marketing_use") or []:
        add(TagType.MARKETING, m)
    for q in result.get("quality_issues") or []:
        add(TagType.QUALITY, q)
    for r in result.get("risk_flags") or []:
        add(TagType.RISK, r)

    # 去重，保序
    seen: set[tuple[str, str]] = set()
    deduped: list[tuple[str, str]] = []
    for t in out:
        if t not in seen:
            seen.add(t)
            deduped.append(t)
    return deduped
