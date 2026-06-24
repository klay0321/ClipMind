"""AI 镜头分析提示词构造（PR-03A）。

提示词版本参与输入指纹；变更提示词语义时递增 ``PROMPT_VERSION``。
强约束：仅输出符合 Schema 的 JSON；缺信息留空，不编造；不确定标 needs_human_review。
"""

from __future__ import annotations

import json
from typing import Any

PROMPT_VERSION = "v1"

_SYSTEM = """你是视频镜头画面理解助手，用于企业素材库的结构化打标。
仅根据给定关键帧画面客观描述，**不要编造**画面中不存在的信息。
要求：
1. 只输出一个 JSON 对象，且必须符合给定 JSON Schema；不要输出多余文字或 Markdown 代码块。
2. 缺乏依据的字段留空字符串或空数组，confidence 给 0..1 的真实把握度。
3. 画面不清晰、产品型号不确定、疑似风险（竞品/水印/隐私/与脚本冲突等）时，
   在 risk_flags / quality_issues 标注，并将 needs_human_review 置为 true。
4. 全部用中文填写文本字段。"""


def build_analysis_prompt(schema: dict[str, Any]) -> str:
    """构造发送给视觉模型的系统/约束提示词（含 JSON Schema）。"""
    schema_text = json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
    return f"{_SYSTEM}\n\nJSON Schema:\n{schema_text}"
