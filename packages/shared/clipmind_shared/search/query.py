"""Gate B：自然语言查询的结构化表示（ParsedSearchQuery）。

把用户自然语言（中文/英文/混合）解析为**严格校验**的结构化条件，供 Hybrid Search 的
各召回通道与结构化过滤使用。设计约束：

- **枚举白名单**：``aspect_ratios`` / ``review_statuses`` 只接受受控取值；非法值在解析层被丢弃，
  绝不进入 SQL。
- **数值范围限制**：时长被 clamp 到 ``[0, MAX_DURATION_SECONDS]``。
- **未知字段忽略策略明确**：``model_config = extra="ignore"`` —— LLM 返回的多余字段被丢弃，
  无法借此注入额外属性。
- **不直接执行模型返回的字段名/表名/排序表达式**：本模型只承载“值”，字段名固定在代码中；
  调用方（``search_service``）用白名单把这些值映射到列与条件，模型注入的任何字符串都只作为
  绑定参数出现。

本模块是纯数据 + 校验，无 I/O，可独立单测。解析器实现见 ``parser.py`` / ``parser_mimo.py``。
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from clipmind_shared.models.enums import ReviewStatus
from clipmind_shared.review.normalize import normalize_name

# ---- 约束常量（变更影响解析输出形状）----
MAX_TERMS_PER_FIELD = 24      # 单个列表字段最多保留的条目数
MAX_TERM_LENGTH = 128         # 单个条目最大字符数
MAX_DURATION_SECONDS = 86_400  # 时长上限（1 天），防御异常巨值
MAX_WARNINGS = 16


class SearchMode(StrEnum):
    """检索模式：决定启用哪些召回通道。"""

    HYBRID = "hybrid"          # 向量 + 词法 + 标签 + 产品（默认）
    SEMANTIC = "semantic"      # 仅向量（不可用时降级为 lexical）
    LEXICAL = "lexical"        # 仅词法 / pg_trgm
    STRUCTURED = "structured"  # 仅结构化（标签 / 产品 / 过滤），不排序于相似度


class AspectRatio(StrEnum):
    """受控画幅白名单（与 asset.width/height 计算比对，容差匹配）。"""

    LANDSCAPE_16_9 = "16:9"
    PORTRAIT_9_16 = "9:16"
    SQUARE_1_1 = "1:1"
    STANDARD_4_3 = "4:3"
    PORTRAIT_3_4 = "3:4"
    CINEMA_21_9 = "21:9"


class ParserStatus(StrEnum):
    """解析器执行状态（对外可见，绝不假装解析成功）。"""

    OK = "ok"              # 解析成功（规则或 LLM）
    DEGRADED = "degraded"  # LLM 解析失败/超时/非法，已降级为规则解析


# 画幅目标比值（width / height）与匹配相对容差
ASPECT_RATIO_VALUES: dict[AspectRatio, float] = {
    AspectRatio.LANDSCAPE_16_9: 16 / 9,
    AspectRatio.PORTRAIT_9_16: 9 / 16,
    AspectRatio.SQUARE_1_1: 1.0,
    AspectRatio.STANDARD_4_3: 4 / 3,
    AspectRatio.PORTRAIT_3_4: 3 / 4,
    AspectRatio.CINEMA_21_9: 21 / 9,
}
ASPECT_RATIO_TOLERANCE = 0.06  # ±6% 容差（覆盖常见编码裁切/取整）


def _sanitize_terms(values: list[str]) -> list[str]:
    """清洗字符串列表：strip、丢空、截断、去重保序、限量。"""
    out: list[str] = []
    seen: set[str] = set()
    for v in values:
        if not isinstance(v, str):
            continue
        s = " ".join(v.split()).strip()
        if not s:
            continue
        if len(s) > MAX_TERM_LENGTH:
            s = s[:MAX_TERM_LENGTH]
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
        if len(out) >= MAX_TERMS_PER_FIELD:
            break
    return out


_STR_LIST_FIELDS = (
    "positive_terms",
    "negative_terms",
    "products",
    "brands",
    "models",
    "skus",
    "scenes",
    "actions",
    "shot_types",
    "marketing_uses",
    "people",
    "objects",
    "quality_requirements",
    "required_risks",
    "excluded_risks",
)


class ParsedSearchQuery(BaseModel):
    """自然语言查询解析结果（严格校验）。"""

    model_config = ConfigDict(extra="ignore")

    original_query: str = ""
    normalized_query: str = ""

    positive_terms: list[str] = []
    negative_terms: list[str] = []

    products: list[str] = []
    brands: list[str] = []
    models: list[str] = []
    skus: list[str] = []

    scenes: list[str] = []
    actions: list[str] = []
    shot_types: list[str] = []
    marketing_uses: list[str] = []
    people: list[str] = []
    objects: list[str] = []

    quality_requirements: list[str] = []
    required_risks: list[str] = []
    excluded_risks: list[str] = []

    min_duration: float | None = None
    max_duration: float | None = None
    aspect_ratios: list[AspectRatio] = []
    review_statuses: list[ReviewStatus] = []

    confirmed_only: bool = False
    include_excluded: bool = False
    allow_similar_scene: bool = True
    allow_similar_action: bool = True

    semantic_text: str = ""

    parser_provider: str = "rulebased"
    parser_model: str = ""
    parser_status: ParserStatus = ParserStatus.OK
    parser_warnings: list[str] = []

    @field_validator(*_STR_LIST_FIELDS, mode="before")
    @classmethod
    def _clean_str_lists(cls, v: object) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):  # 容忍 LLM 返回单字符串
            v = [v]
        if not isinstance(v, (list, tuple)):
            return []
        return _sanitize_terms([x for x in v if isinstance(x, str)])

    @field_validator("aspect_ratios", "review_statuses", mode="before")
    @classmethod
    def _coerce_enum_list(cls, v: object) -> list:
        if v is None:
            return []
        if isinstance(v, (str,)):
            v = [v]
        if not isinstance(v, (list, tuple)):
            return []
        # 去重保序；非法成员由 pydantic 后续校验拒绝（解析层已预过滤）
        out: list = []
        seen: set = set()
        for x in v:
            if x in seen:
                continue
            seen.add(x)
            out.append(x)
        return out

    @field_validator("parser_warnings", mode="before")
    @classmethod
    def _clean_warnings(cls, v: object) -> list[str]:
        if not isinstance(v, (list, tuple)):
            return []
        return [str(x)[:MAX_TERM_LENGTH] for x in v][:MAX_WARNINGS]

    @model_validator(mode="after")
    def _finalize(self) -> ParsedSearchQuery:
        # 时长 clamp 到合法区间；min > max 视为无效上限，置空并告警
        for attr in ("min_duration", "max_duration"):
            val = getattr(self, attr)
            if val is not None:
                if val < 0:
                    val = 0.0
                if val > MAX_DURATION_SECONDS:
                    val = float(MAX_DURATION_SECONDS)
                setattr(self, attr, float(val))
        if (
            self.min_duration is not None
            and self.max_duration is not None
            and self.min_duration > self.max_duration
        ):
            self.parser_warnings = [*self.parser_warnings, "min_duration_gt_max_duration"][
                :MAX_WARNINGS
            ]
            self.max_duration = None
        # 兜底 normalized_query / semantic_text
        if not self.normalized_query:
            self.normalized_query = normalize_name(self.original_query)
        if not self.semantic_text:
            self.semantic_text = self.original_query.strip() or self.normalized_query
        return self

    # ---- 便捷只读视图 ----
    @property
    def has_structured_signal(self) -> bool:
        """是否存在任何结构化召回/过滤信号（用于决定 structured 模式是否有效）。"""
        return any(
            [
                self.products,
                self.brands,
                self.models,
                self.skus,
                self.scenes,
                self.actions,
                self.shot_types,
                self.marketing_uses,
                self.required_risks,
                self.excluded_risks,
                self.quality_requirements,
                self.aspect_ratios,
                self.review_statuses,
                self.min_duration is not None,
                self.max_duration is not None,
                self.confirmed_only,
            ]
        )

    @property
    def all_terms(self) -> list[str]:
        """用于词法召回的关键词集合（正向词 + 结构化值，去重保序）。"""
        terms: list[str] = []
        seen: set[str] = set()
        for group in (
            self.positive_terms,
            self.products,
            self.brands,
            self.models,
            self.skus,
            self.scenes,
            self.actions,
            self.shot_types,
            self.marketing_uses,
            self.people,
            self.objects,
        ):
            for t in group:
                k = t.lower()
                if k not in seen:
                    seen.add(k)
                    terms.append(t)
        return terms
