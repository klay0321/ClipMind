"""OBS：单素材链路诊断与管线健康的响应模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

StageStatus = Literal["ok", "pending", "lagging", "failed", "excluded", "not_applicable"]


class TraceStageOut(BaseModel):
    """单个环节的诊断结果。

    status 语义：
    - ok             该环节已完成且结果可用
    - pending        正在处理/排队中（有 run 在跑）
    - lagging        应该发生但还没发生（无失败记录，多半在等队列或未触发）
    - failed         有明确失败记录（error 见 detail）
    - excluded       按规则排除（不是故障，如驳回后文档 excluded）
    - not_applicable 该素材类型没有这个环节
    """

    stage: Literal["scan", "derive", "ai", "review", "document", "embedding"]
    title: str
    status: StageStatus
    detail: dict[str, Any]
    hint: str


class AssetTraceOut(BaseModel):
    asset_id: int
    media_kind: str
    filename: str
    stages: list[TraceStageOut]
    generated_at: datetime


class PipelineHealthOut(BaseModel):
    """全局管线健康：各环节滞后/失败计数 + 队列深度。

    counters 键与含义（0 = 健康）：
    - assets_no_shots        视频已入库但无任何镜头
    - shots_ai_missing       ready 镜头缺 AI 分析
    - ai_failed              AI 镜头分析失败行
    - img_ai_missing         已索引图片缺 AI 理解
    - runs_stuck_running     运行超 2 小时未结束的分析 run
    - shot_docs_missing      ready 镜头缺检索文档
    - shot_docs_degraded     镜头文档向量降级
    - asset_docs_missing     已索引素材缺素材级检索文档
    - visual_emb_failed      视觉向量失败行
    """

    counters: dict[str, int]
    queues: dict[str, int | None]
    generated_at: datetime
