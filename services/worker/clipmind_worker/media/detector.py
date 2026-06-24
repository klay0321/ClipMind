"""可替换的镜头检测接口与实现。

设计：
- `ShotDetector` 协议 + 两个实现：PySceneDetect 内容检测（主）、固定时长切分（兜底）。
- `postprocess_boundaries` 是纯函数：短镜头合并、长镜头继续拆分、首尾安全余量、边界归一化。
  纯函数便于无 ffmpeg/无 DB 的快速单测。
- `detect_shots` 为编排：主检测失败或无明显转场时回退到固定切分，最后统一做后处理。

镜头结果保证：顺序、不重叠、不超过总时长、无零时长、无明显转场仍有结果、单镜头短视频得到一个有效镜头。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

logger = logging.getLogger(__name__)

_EPS = 1e-6


@dataclass(frozen=True)
class ShotConfig:
    """镜头检测/切分参数（初始默认值，可被 WorkerSettings/环境变量覆盖）。"""

    detector_type: str = "pyscenedetect"
    scene_threshold: float = 27.0
    min_shot_duration: float = 1.0
    max_shot_duration: float = 12.0
    fallback_segment_duration: float = 5.0
    head_padding: float = 0.0
    tail_padding: float = 0.0

    def to_snapshot(self) -> dict[str, Any]:
        return {
            "detector_type": self.detector_type,
            "scene_threshold": self.scene_threshold,
            "min_shot_duration": self.min_shot_duration,
            "max_shot_duration": self.max_shot_duration,
            "fallback_segment_duration": self.fallback_segment_duration,
            "head_padding": self.head_padding,
            "tail_padding": self.tail_padding,
        }


@dataclass
class ShotBoundary:
    start: float
    end: float
    detector_type: str = "fixed"
    confidence: float | None = None

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class _Seg:
    start: float
    end: float
    confidence: float | None = None

    @property
    def dur(self) -> float:
        return self.end - self.start


class ShotDetector(Protocol):
    """镜头检测接口：返回覆盖视频的 (start, end) 秒边界列表（可能为整片单段）。"""

    name: str

    def detect(
        self, video_path: str, *, duration: float, config: ShotConfig
    ) -> list[ShotBoundary]: ...


@dataclass
class FixedDurationDetector:
    """固定时长切分（兜底/无明显转场时使用）。纯计算，不依赖外部库。"""

    name: str = field(default="fixed", init=False)

    def detect(
        self, video_path: str, *, duration: float, config: ShotConfig
    ) -> list[ShotBoundary]:
        return fixed_segments(0.0, duration, config.fallback_segment_duration)


@dataclass
class PySceneDetectDetector:
    """PySceneDetect 内容检测（主）。lazy import，导入/运行失败由编排层回退。"""

    name: str = field(default="pyscenedetect", init=False)

    def detect(
        self, video_path: str, *, duration: float, config: ShotConfig
    ) -> list[ShotBoundary]:
        # lazy import：缺少 scenedetect/opencv 时不影响模块导入与纯逻辑测试
        from scenedetect import ContentDetector, detect

        scenes = detect(video_path, ContentDetector(threshold=config.scene_threshold))
        boundaries: list[ShotBoundary] = []
        for start_tc, end_tc in scenes:
            boundaries.append(
                ShotBoundary(
                    start=float(start_tc.get_seconds()),
                    end=float(end_tc.get_seconds()),
                    detector_type="pyscenedetect",
                )
            )
        return boundaries


def fixed_segments(lo: float, hi: float, seg: float) -> list[ShotBoundary]:
    """在 [lo, hi] 上按 seg 秒等分（最后一段可能偏短）。"""
    if seg <= 0:
        seg = max(hi - lo, _EPS)
    out: list[ShotBoundary] = []
    cur = lo
    while cur < hi - _EPS:
        nxt = min(cur + seg, hi)
        out.append(ShotBoundary(start=cur, end=nxt, detector_type="fixed"))
        cur = nxt
    if not out:
        out.append(ShotBoundary(start=lo, end=max(hi, lo + _EPS), detector_type="fixed"))
    return out


def _merge_short(segs: list[_Seg], min_dur: float) -> list[_Seg]:
    """合并过短镜头：短段并入相邻段；单段短视频原样保留。"""
    if min_dur <= 0:
        return segs
    changed = True
    while changed and len(segs) > 1:
        changed = False
        for i, s in enumerate(segs):
            if s.dur < min_dur - _EPS:
                if i > 0:  # 并入前一段
                    segs[i - 1].end = s.end
                    del segs[i]
                else:  # 第一段并入后一段
                    segs[i + 1].start = s.start
                    del segs[i]
                changed = True
                break
    return segs


def _split_long(segs: list[_Seg], max_dur: float) -> list[_Seg]:
    """拆分过长镜头：超过 max 的段等分为多段（每段 <= max）。"""
    if max_dur <= 0:
        return segs
    out: list[_Seg] = []
    for s in segs:
        if s.dur <= max_dur + _EPS:
            out.append(s)
            continue
        import math

        n = math.ceil(s.dur / max_dur)
        step = s.dur / n
        for k in range(n):
            a = s.start + k * step
            b = s.end if k == n - 1 else s.start + (k + 1) * step
            out.append(_Seg(start=a, end=b, confidence=s.confidence))
    return out


def postprocess_boundaries(
    raw: list[ShotBoundary], *, duration: float, config: ShotConfig
) -> list[ShotBoundary]:
    """对原始边界做：首尾余量裁剪、clamp、短合并、长拆分、归一化排序。"""
    duration = max(duration, 0.0)
    lo = min(max(config.head_padding, 0.0), duration)
    hi = max(duration - max(config.tail_padding, 0.0), lo)
    if hi - lo <= _EPS:  # 首尾余量把整片裁空 → 退回整片
        lo, hi = 0.0, max(duration, _EPS)

    segs: list[_Seg] = []
    for b in sorted(raw, key=lambda x: x.start):
        s = max(b.start, lo)
        e = min(b.end, hi)
        if e - s > _EPS:
            segs.append(_Seg(start=s, end=e, confidence=b.confidence))

    if not segs:
        segs = [_Seg(start=lo, end=hi)]

    segs = _merge_short(segs, config.min_shot_duration)
    segs = _split_long(segs, config.max_shot_duration)

    out: list[ShotBoundary] = []
    for s in segs:
        start = max(s.start, 0.0)
        end = min(s.end, duration if duration > _EPS else s.end)
        if end - start <= _EPS:
            continue
        out.append(
            ShotBoundary(
                start=round(start, 3),
                end=round(end, 3),
                detector_type=config.detector_type,
                confidence=s.confidence,
            )
        )
    if not out:  # 极端兜底：始终至少一个有效镜头
        out.append(
            ShotBoundary(start=0.0, end=round(max(duration, _EPS), 3),
                        detector_type=config.detector_type)
        )
    return out


def make_detector(config: ShotConfig) -> ShotDetector:
    if config.detector_type == "fixed":
        return FixedDurationDetector()
    return PySceneDetectDetector()


def detect_shots(
    video_path: str,
    *,
    duration: float,
    config: ShotConfig,
    detector: ShotDetector | None = None,
) -> list[ShotBoundary]:
    """编排：主检测 → 无转场/失败回退固定切分 → 统一后处理。"""
    det = detector or make_detector(config)
    raw: list[ShotBoundary] = []
    try:
        raw = det.detect(video_path, duration=duration, config=config)
    except Exception as exc:  # noqa: BLE001 - 检测器失败回退兜底，不中断处理
        logger.warning("镜头检测器 %s 失败，回退固定切分: %s", getattr(det, "name", "?"), exc)
        raw = []

    # 少于 2 段（无明显转场或失败）→ 固定切分兜底
    if len(raw) < 2:
        raw = fixed_segments(0.0, duration, config.fallback_segment_duration)

    return postprocess_boundaries(raw, duration=duration, config=config)
