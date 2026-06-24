"""AI 镜头分析的结构化输出契约（PR-03A）。

以 Pydantic 模型作为权威 Schema，既用于校验 provider 返回，也用 ``model_json_schema()``
导出 JSON Schema 供提示词约束与对外展示。字段对齐 PRODUCT_REQUIREMENTS 7.6.2。

原则（7.6.3）：所有字段**允许为空**，缺信息留空而非编造；校验失败由编排层重试，
多次失败入失败态（PR-03B 入人工队列）。本 PR 不把结果拆解为标签/产品表。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# Schema 语义版本（与 constants.AI_SCHEMA_VERSION 对应；变更字段含义时递增）
SHOT_ANALYSIS_SCHEMA_VERSION = 1


class ProductInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = ""
    model: str = ""
    color: str = ""
    state: str = ""


class ShotAnalysisResult(BaseModel):
    """单镜头 AI 画面理解结构化结果（缺字段留空，不编造）。"""

    model_config = ConfigDict(extra="ignore")

    one_line: str = ""            # 一句话画面描述
    detailed: str = ""           # 详细画面描述
    product: ProductInfo = Field(default_factory=ProductInfo)
    scene: str = ""              # 场景
    action: str = ""             # 动作
    shot_type: str = ""          # 镜头类型
    subject: str = ""            # 人物主体
    marketing_use: list[str] = Field(default_factory=list)   # 营销用途
    selling_points: list[str] = Field(default_factory=list)  # 卖点
    visible_text: list[str] = Field(default_factory=list)    # 可见文字
    logo_brand: list[str] = Field(default_factory=list)      # Logo/品牌
    quality_issues: list[str] = Field(default_factory=list)  # 质量问题
    risk_flags: list[str] = Field(default_factory=list)      # 风险项
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)   # 置信度 0..1
    needs_human_review: bool = False                          # 是否需人工确认
    search_keywords: list[str] = Field(default_factory=list)  # 搜索关键词
    recommended_scenes: list[str] = Field(default_factory=list)  # 推荐使用场景


def shot_analysis_json_schema() -> dict[str, Any]:
    """导出 JSON Schema（供提示词约束与前端/文档展示）。"""
    return ShotAnalysisResult.model_json_schema()


def validate_shot_analysis(data: dict[str, Any]) -> ShotAnalysisResult:
    """校验 provider 返回的结构化数据；非法将抛 pydantic ValidationError。"""
    return ShotAnalysisResult.model_validate(data)
