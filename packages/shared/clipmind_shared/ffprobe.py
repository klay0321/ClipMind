"""FFprobe 视频信息封装。

- 只读探测，绝不修改源文件。
- 用 `--` 阻断文件名选项注入；绝不使用 shell=True。
- 任何失败都抛 ProbeError（携带可分类的 reason），由调用方记录到 error_message，
  并保证不中断整体扫描。
"""

from __future__ import annotations

import json
import subprocess

from pydantic import BaseModel


class ProbeError(Exception):
    """FFprobe 探测失败。reason 为可分类原因，detail 为简短细节。"""

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


class ProbeResult(BaseModel):
    duration: float | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    orientation: str | None = None  # landscape / portrait / square
    has_audio: bool = False


def _to_float(value: object) -> float | None:
    try:
        if value is None:
            return None
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _to_int(value: object) -> int | None:
    try:
        if value is None:
            return None
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def parse_fps(rate: str | None) -> float | None:
    """解析 ffprobe 的 r_frame_rate（形如 "30000/1001"）。"""
    if not rate:
        return None
    try:
        if "/" in rate:
            num, den = rate.split("/", 1)
            den_f = float(den)
            if den_f == 0:
                return None
            return round(float(num) / den_f, 3)
        return float(rate)
    except (TypeError, ValueError):
        return None


def _rotation(video: dict) -> int:
    """读取旋转角度（tags.rotate 或 side_data_list 的 rotation/displaymatrix）。"""
    tags = video.get("tags") or {}
    if "rotate" in tags:
        val = _to_float(tags.get("rotate"))
        if val is not None:
            return int(val)
    for side in video.get("side_data_list") or []:
        if "rotation" in side:
            val = _to_float(side.get("rotation"))
            if val is not None:
                return int(val)
    return 0


def _orientation(width: int | None, height: int | None) -> str | None:
    if not width or not height:
        return None
    if width > height:
        return "landscape"
    if height > width:
        return "portrait"
    return "square"


def probe_video(
    path: str, *, ffprobe_path: str = "ffprobe", timeout: float = 30.0
) -> ProbeResult:
    """对单个视频文件运行 ffprobe，返回结构化信息。

    Raises:
        ProbeError: 二进制缺失/超时/非零退出/JSON 解析失败/无视频流。
    """
    cmd = [
        ffprobe_path,
        "-v",
        "error",
        "-hide_banner",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        "--",
        path,
    ]
    try:
        proc = subprocess.run(  # noqa: S603 - 固定参数列表，无 shell
            cmd, capture_output=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise ProbeError("timeout", f"ffprobe 超时(>{timeout}s)") from exc
    except FileNotFoundError as exc:
        raise ProbeError("ffprobe_not_found", "未找到 ffprobe 可执行文件") from exc

    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", "replace").strip()
        raise ProbeError("ffprobe_failed", stderr[:500])

    try:
        data = json.loads(proc.stdout.decode("utf-8", "replace"))
    except json.JSONDecodeError as exc:
        raise ProbeError("invalid_json", str(exc)) from exc

    streams = data.get("streams") or []
    fmt = data.get("format") or {}
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    if video is None:
        raise ProbeError("no_video_stream", "未发现视频流")

    duration = _to_float(fmt.get("duration"))
    if duration is None:
        duration = _to_float(video.get("duration"))

    width = _to_int(video.get("width"))
    height = _to_int(video.get("height"))
    fps = parse_fps(video.get("r_frame_rate") or video.get("avg_frame_rate"))

    # 旋转校正：竖拍视频元数据常为横向 + rotate=90/270
    rotation = _rotation(video)
    if rotation % 180 == 90 and width and height:
        width, height = height, width

    return ProbeResult(
        duration=duration,
        width=width,
        height=height,
        fps=fps,
        video_codec=video.get("codec_name"),
        audio_codec=(audio.get("codec_name") if audio else None),
        orientation=_orientation(width, height),
        has_audio=audio is not None,
    )


def ffprobe_version(ffprobe_path: str = "ffprobe", timeout: float = 5.0) -> str | None:
    """返回 ffprobe 版本首行；不可用时返回 None（健康检查用）。"""
    try:
        proc = subprocess.run(  # noqa: S603
            [ffprobe_path, "-version"], capture_output=True, timeout=timeout, check=False
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    first_line = proc.stdout.decode("utf-8", "replace").splitlines()
    return first_line[0].strip() if first_line else None
