"""PR-05 Gate A：脚本拆段的结构化表示（ParsedScript / ParsedScriptSegment）。

把用户粘贴的脚本（中文/英文/混合）解析为**严格校验**的分段结构，供后续镜头匹配
（Gate B，复用 Hybrid Search / Description Match）使用。设计约束与 ``ParsedSearchQuery``
（Gate B）一致：

- **枚举白名单**：``parser_status`` 只接受受控取值；非法值在解析层丢弃。
- **数值/数量上限**：段落数、单段长度、单字段条目数、时长均被 clamp，防御 LLM 异常输出。
- **未知字段忽略**：``extra="ignore"`` —— LLM 返回的多余字段被丢弃，无法借此注入属性。
- **不承载字段名/表名/排序表达式**：本模型只承载"值"；调用方用白名单把这些值映射到检索条件，
  模型注入的任何字符串都只作为绑定参数出现。绝不把 LLM 文本直接拼进 SQL。
- **LLM 不返回 / 不决定 shot_id**：匹配由检索内核完成，LLM 只产出画面需求。

本模块为纯数据 + 校验，无 I/O，可独立单测。解析器实现见 ``parser.py`` / ``parser_mimo.py``。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from clipmind_shared.constants import SCRIPT_PARSE_SCHEMA_VERSION
from clipmind_shared.models.enums import ScriptParseStatus
from clipmind_shared.review.normalize import normalize_name

# ---- 约束常量（变更影响解析输出形状）----
MAX_SEGMENTS = 50              # 单脚本最多段落数
MAX_SEGMENT_TEXT_LENGTH = 2000  # 单段文案最大字符数
MAX_SCRIPT_LENGTH = 20_000     # 整脚本最大字符数
MAX_TERMS_PER_FIELD = 24       # 单个列表字段最多保留条目数
MAX_TERM_LENGTH = 128          # 单个条目最大字符数
MAX_DURATION_SECONDS = 3_600   # 单段目标时长上限（秒）
MAX_WARNINGS = 16


def _sanitize_terms(values: object) -> list[str]:
    """清洗字符串列表：容忍单串、strip、丢空、截断、去重保序、限量。"""
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, (list, tuple)):
        return []
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
    "products",
    "scenes",
    "actions",
    "shot_types",
    "marketing_uses",
    "people",
    "objects",
    "quality_requirements",
    "selling_points",
    "must_include",
    "negative_terms",
    "excluded_risks",
)


class ParsedScriptSegment(BaseModel):
    """单个脚本段落的结构化画面需求（缺信息留空，不编造）。"""

    model_config = ConfigDict(extra="ignore")

    order_index: int = 0
    text: str = ""               # 段落原始文案
    visual_requirement: str = ""  # 画面需求（语义检索文本；空则回退 text）

    target_duration_min: float | None = None
    target_duration_max: float | None = None

    products: list[str] = []
    scenes: list[str] = []
    actions: list[str] = []
    shot_types: list[str] = []
    marketing_uses: list[str] = []
    people: list[str] = []
    objects: list[str] = []
    quality_requirements: list[str] = []
    selling_points: list[str] = []
    must_include: list[str] = []       # 必须出现内容
    negative_terms: list[str] = []     # 禁止出现内容（软）
    excluded_risks: list[str] = []     # 必须排除的风险标签（硬）

    allow_similar_scene: bool = True
    allow_similar_action: bool = True

    parser_warnings: list[str] = []

    @field_validator(*_STR_LIST_FIELDS, mode="before")
    @classmethod
    def _clean_str_lists(cls, v: object) -> list[str]:
        return _sanitize_terms(v)

    @field_validator("parser_warnings", mode="before")
    @classmethod
    def _clean_warnings(cls, v: object) -> list[str]:
        if not isinstance(v, (list, tuple)):
            return []
        return [str(x)[:MAX_TERM_LENGTH] for x in v][:MAX_WARNINGS]

    @field_validator("order_index", mode="before")
    @classmethod
    def _coerce_order(cls, v: object) -> int:
        try:
            return max(0, int(v))
        except (TypeError, ValueError):
            return 0

    @model_validator(mode="after")
    def _finalize(self) -> ParsedScriptSegment:
        # 文案/画面需求截断
        if self.text and len(self.text) > MAX_SEGMENT_TEXT_LENGTH:
            self.text = self.text[:MAX_SEGMENT_TEXT_LENGTH]
        if self.visual_requirement and len(self.visual_requirement) > MAX_SEGMENT_TEXT_LENGTH:
            self.visual_requirement = self.visual_requirement[:MAX_SEGMENT_TEXT_LENGTH]
        # 时长 clamp 到合法区间；min > max 视为无效上限，置空并告警
        for attr in ("target_duration_min", "target_duration_max"):
            val = getattr(self, attr)
            if val is not None:
                try:
                    val = float(val)
                except (TypeError, ValueError):
                    setattr(self, attr, None)
                    continue
                val = max(0.0, min(val, float(MAX_DURATION_SECONDS)))
                setattr(self, attr, val)
        if (
            self.target_duration_min is not None
            and self.target_duration_max is not None
            and self.target_duration_min > self.target_duration_max
        ):
            self.parser_warnings = [
                *self.parser_warnings,
                "target_duration_min_gt_max",
            ][:MAX_WARNINGS]
            self.target_duration_max = None
        # 画面需求兜底：空则用文案
        if not self.visual_requirement:
            self.visual_requirement = self.text.strip()
        return self

    @property
    def normalized_text(self) -> str:
        return normalize_name(self.text)

    @property
    def has_structured_signal(self) -> bool:
        return any(
            [
                self.products,
                self.scenes,
                self.actions,
                self.shot_types,
                self.marketing_uses,
                self.excluded_risks,
                self.target_duration_min is not None,
                self.target_duration_max is not None,
            ]
        )


class ParsedScript(BaseModel):
    """脚本拆段解析结果（严格校验）。"""

    model_config = ConfigDict(extra="ignore")

    segments: list[ParsedScriptSegment] = []

    parser_provider: str = "rulebased"
    parser_model: str = ""
    parser_status: ScriptParseStatus = ScriptParseStatus.OK
    parser_warnings: list[str] = []
    schema_version: int = SCRIPT_PARSE_SCHEMA_VERSION

    @field_validator("parser_warnings", mode="before")
    @classmethod
    def _clean_warnings(cls, v: object) -> list[str]:
        if not isinstance(v, (list, tuple)):
            return []
        return [str(x)[:MAX_TERM_LENGTH] for x in v][:MAX_WARNINGS]

    @model_validator(mode="after")
    def _finalize(self) -> ParsedScript:
        # 段落数量上限 + 重排 order_index 为 0..n-1（稳定、连续、无重复）
        segs = self.segments[:MAX_SEGMENTS]
        if len(self.segments) > MAX_SEGMENTS:
            self.parser_warnings = [
                *self.parser_warnings,
                f"segments_truncated_to_{MAX_SEGMENTS}",
            ][:MAX_WARNINGS]
        for i, seg in enumerate(segs):
            seg.order_index = i
        self.segments = segs
        return self
