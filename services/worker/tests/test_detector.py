"""镜头边界后处理纯逻辑测试（无 ffmpeg、无 DB）。"""

from __future__ import annotations

import pytest

from clipmind_worker.media.detector import (
    FixedDurationDetector,
    ShotBoundary,
    ShotConfig,
    detect_shots,
    fixed_segments,
    postprocess_boundaries,
)

EPS = 1e-3


def _assert_valid(shots: list[ShotBoundary], duration: float) -> None:
    assert shots, "至少应有一个镜头"
    prev_end = 0.0
    for s in shots:
        assert s.start >= -EPS, f"start>=0: {s.start}"
        assert s.end <= duration + EPS, f"end<=duration: {s.end} <= {duration}"
        assert s.duration > EPS, f"无零时长: {s.duration}"
        assert s.start >= prev_end - EPS, f"不重叠: {s.start} >= {prev_end}"
        prev_end = s.end
    # 序号顺序：start 单调不减
    starts = [s.start for s in shots]
    assert starts == sorted(starts)


def test_fixed_segments_basic():
    segs = fixed_segments(0.0, 10.0, 4.0)
    assert [(round(s.start), round(s.end)) for s in segs] == [(0, 4), (4, 8), (8, 10)]


def test_fixed_segments_single_short():
    segs = fixed_segments(0.0, 2.0, 5.0)
    assert len(segs) == 1
    assert segs[0].start == 0.0 and segs[0].end == 2.0


def test_postprocess_orders_and_clamps():
    cfg = ShotConfig(min_shot_duration=0.0, max_shot_duration=1000.0)
    raw = [ShotBoundary(0.0, 3.0), ShotBoundary(3.0, 6.0), ShotBoundary(6.0, 9.0)]
    shots = postprocess_boundaries(raw, duration=9.0, config=cfg)
    _assert_valid(shots, 9.0)
    assert len(shots) == 3


def test_postprocess_clamps_overshoot_duration():
    cfg = ShotConfig(min_shot_duration=0.0, max_shot_duration=1000.0)
    raw = [ShotBoundary(0.0, 5.0), ShotBoundary(5.0, 99.0)]  # 第二段超出总时长
    shots = postprocess_boundaries(raw, duration=8.0, config=cfg)
    _assert_valid(shots, 8.0)
    assert shots[-1].end <= 8.0 + EPS


def test_merge_short_shots():
    cfg = ShotConfig(min_shot_duration=2.0, max_shot_duration=1000.0)
    raw = [ShotBoundary(0.0, 0.5), ShotBoundary(0.5, 1.0), ShotBoundary(1.0, 5.0)]
    shots = postprocess_boundaries(raw, duration=5.0, config=cfg)
    _assert_valid(shots, 5.0)
    assert all(s.duration >= 2.0 - EPS for s in shots)


def test_split_long_shots():
    cfg = ShotConfig(min_shot_duration=0.0, max_shot_duration=5.0)
    raw = [ShotBoundary(0.0, 17.0)]
    shots = postprocess_boundaries(raw, duration=17.0, config=cfg)
    _assert_valid(shots, 17.0)
    assert all(s.duration <= 5.0 + EPS for s in shots)
    assert len(shots) >= 4


def test_single_short_video_one_shot():
    cfg = ShotConfig(min_shot_duration=3.0, max_shot_duration=12.0)
    # 比 min 还短的整片：无法再合并 → 保留一个有效镜头
    shots = postprocess_boundaries([ShotBoundary(0.0, 1.2)], duration=1.2, config=cfg)
    _assert_valid(shots, 1.2)
    assert len(shots) == 1


def test_no_scenes_fallback_via_detect_shots():
    cfg = ShotConfig(detector_type="fixed", min_shot_duration=0.0,
                     max_shot_duration=12.0, fallback_segment_duration=5.0)
    shots = detect_shots("/nonexistent.mp4", duration=12.0, config=cfg,
                         detector=FixedDurationDetector())
    _assert_valid(shots, 12.0)
    assert len(shots) >= 2  # 12s / 5s → 3 段


def test_head_tail_padding_trims_range():
    cfg = ShotConfig(min_shot_duration=0.0, max_shot_duration=1000.0,
                     head_padding=1.0, tail_padding=1.0)
    shots = postprocess_boundaries([ShotBoundary(0.0, 10.0)], duration=10.0, config=cfg)
    _assert_valid(shots, 10.0)
    assert shots[0].start >= 1.0 - EPS
    assert shots[-1].end <= 9.0 + EPS


def test_detector_exception_falls_back():
    class _Boom:
        name = "boom"

        def detect(self, *a, **k):
            raise RuntimeError("backend missing")

    cfg = ShotConfig(min_shot_duration=0.0, max_shot_duration=12.0,
                     fallback_segment_duration=4.0)
    shots = detect_shots("/x.mp4", duration=12.0, config=cfg, detector=_Boom())
    _assert_valid(shots, 12.0)
    assert len(shots) >= 2


@pytest.mark.parametrize("dur", [0.3, 1.0, 7.5, 30.0, 120.0])
def test_various_durations_stay_valid(dur):
    cfg = ShotConfig(detector_type="fixed", min_shot_duration=1.0,
                     max_shot_duration=12.0, fallback_segment_duration=5.0)
    shots = detect_shots("/x.mp4", duration=dur, config=cfg, detector=FixedDurationDetector())
    _assert_valid(shots, dur)
