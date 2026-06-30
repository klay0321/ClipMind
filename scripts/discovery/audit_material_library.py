#!/usr/bin/env python3
"""ClipMind 跨境电商素材库 **只读** 盘点脚本（Phase 0 / Discovery）。

设计目标
========
对一个本地/NAS 素材根目录做严格只读审计，产出可供运营与工程审阅的盘点结果，
为后续"产品识别 / 使用血缘 / 使用感知检索 / 分镜匹配 / 评测基线"提供事实依据。

最高优先级安全约束（务必遵守）
------------------------------
1. 绝不对源目录执行任何写操作：不创建 sidecar、不生成同目录缩略图、不改 mtime。
2. 源文件只以二进制只读模式 ``open(path, "rb")`` 打开（仅在指纹计算时）。
3. 探测一律走 ffprobe 只读子进程，并用 ``--`` 阻断文件名选项注入，绝不 ``shell=True``。
4. 不跟随危险 symlink（目录软链直接跳过并记录，文件软链逃逸出根也跳过）。
5. 所有输出只写入 ``--output`` 指定目录（应为仓库下被 git 忽略的 ``.local/...``）。
6. 脚本本身不硬编码任何用户绝对路径；可提交产物不写入完整绝对路径（输出脱敏）。
7. 运行前后核对源目录文件数 / 抽样大小 / 抽样 mtime，确认全程只读。

证据分层
--------
本脚本只产出两类信息：``事实``（文件 stat / ffprobe 结果）与 ``规则推断``
（基于目录、文件名、后缀、时长、分辨率等的候选分类）。
``AI 推断`` 与 ``人工确认`` 留待后续阶段，绝不在此自动写入生产数据库。

用法
----
    python scripts/discovery/audit_material_library.py \
        --root "<素材根目录>" --output ".local/material-audit"
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------- #
# 常量：扩展名 / 关键词 / 产品映射
# --------------------------------------------------------------------------- #

IMAGE_EXTS = {
    ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif",
    ".tif", ".tiff", ".heic", ".heif",
}
VIDEO_EXTS = {
    ".mp4", ".mov", ".m4v", ".avi", ".mkv", ".wmv", ".flv",
    ".webm", ".mpg", ".mpeg", ".mts", ".m2ts", ".3gp",
}
# 剪辑工程 / 时间线交换格式（.xml 含义不确定 → 标注 needs_human）
EDITOR_PROJECT_EXTS = {
    ".prproj", ".fcpxml", ".edl", ".veg", ".drp", ".aep",
    ".kdenlive", ".xml",
}
SUBTITLE_EXTS = {".srt", ".ass", ".vtt", ".sub"}
# 系统 / 缩略图垃圾文件（不计入业务素材）
JUNK_NAMES = {"thumbs.db", ".ds_store", "desktop.ini"}
JUNK_EXTS = {".db", ".ini", ".tmp"}

# "已使用" / 成片 等历史证据关键词（小写匹配；中文按原文匹配）
USED_KEYWORDS = ["已使用", "已用", "用过", "usedclip"]
USED_KEYWORDS_AMBIGUOUS = ["used", "use_", "_use", "done"]  # 英文易误判 → needs_human
FINAL_KEYWORDS = [
    "成片", "正片", "成品", "完成片", "宣传片", "主图视频", "带货",
    "final", "export", "导出", "output", "成稿",
]

# 产品族 / 变体关键词映射（用于规则推断的产品候选；只能是候选，不可最终确认）
# 每项: (family, variant_or_None, [keywords...])
PRODUCT_RULES: list[tuple[str, str | None, list[str]]] = [
    ("恶魔之眼", "软屏", ["恶魔之眼软屏", "软屏", "soft screen", "softscreen"]),
    ("恶魔之眼", "硬屏", ["恶魔之眼硬屏", "硬屏", "hard screen", "hardscreen"]),
    ("恶魔之眼", None, ["恶魔之眼", "demon eye", "evil eye", "demoneye"]),
    ("车换挡握把", "十字架档把", ["十字架档把", "十字架挡把", "十字档把"]),
    ("车换挡握把", None, ["换挡握把", "握把", "档把", "挡把", "换挡", "档位",
                       "gear shift", "shift knob", "gear knob", "knob"]),
    ("小键盘", "mini键盘", ["mini键盘", "迷你键盘", "mini keyboard", "minikeyboard"]),
    ("小键盘", None, ["小键盘", "键盘", "keyboard"]),
]
# 仅表示拍摄品类、不等于具体产品（需人工绑定到产品）
CATEGORY_KEYWORDS = ["汽配", "数码", "素材", "auto parts", "digital"]

# 软屏 vs 硬屏 人工差异特征探针（只作为问题列出，不作断言）
SOFT_VS_HARD_QUESTIONS = [
    "屏体是否可弯曲贴合曲面（软屏柔性 vs 硬屏刚性）",
    "屏体边缘/包边结构差异",
    "排线/接线方式与位置",
    "安装方式（曲面贴合 vs 平面安装）",
    "厚度与背板结构",
    "外包装与丝印标识",
    "SKU / 货号差异",
]

DEFAULT_VERIFY_SAMPLE = 40
QUICK_HASH_BYTES = 65536  # 头尾各取 64KB 做 quick hash
CACHE_FLUSH_EVERY = 25


# --------------------------------------------------------------------------- #
# 数据结构
# --------------------------------------------------------------------------- #


@dataclass
class FileRecord:
    relpath: str
    top_dir: str
    parent_dir: str
    filename: str
    ext: str
    kind: str  # image / video / editor_project / subtitle / junk / other
    size_bytes: int
    mtime_ns: int
    mtime_iso: str
    # 媒体事实（ffprobe）
    width: int | None = None
    height: int | None = None
    duration_sec: float | None = None
    fps: float | None = None
    video_codec: str | None = None
    has_audio: bool | None = None
    orientation: str | None = None
    probe_status: str = "pending"  # ok / skipped / error / not_media
    error_reason: str = ""
    # 规则推断
    classification: str = "unknown"
    classification_confidence: str = "low"
    inference_type: str = "rule"  # fact / rule / ai / human
    evidence: list[str] = field(default_factory=list)
    needs_human: bool = True
    product_family: str | None = None
    product_variant: str | None = None
    # 指纹（仅去重候选才计算）
    quick_hash: str | None = None
    sha256: str | None = None


@dataclass
class ErrorRecord:
    relpath: str
    stage: str
    error_reason: str
    detail: str = ""


# --------------------------------------------------------------------------- #
# 路径安全工具
# --------------------------------------------------------------------------- #


def _real(path: str | os.PathLike[str]) -> str:
    return os.path.realpath(os.path.abspath(str(path)))


def is_within(child: str, parent: str) -> bool:
    """child 的 realpath 是否被 parent 的 realpath 包含（含相等）。"""
    parent_r = _real(parent)
    child_r = _real(child)
    try:
        return os.path.commonpath([parent_r, child_r]) == parent_r
    except ValueError:
        # 不同盘符等无公共路径
        return False


def assert_output_safe(root: str, output: str) -> None:
    """输出目录绝不能落在源根目录内（防止污染源目录）。"""
    if is_within(output, root):
        raise SystemExit(
            f"[FATAL] 输出目录位于源目录内，已拒绝运行以保护源目录只读：output={output}"
        )


# --------------------------------------------------------------------------- #
# 文件遍历（只读、symlink 安全）
# --------------------------------------------------------------------------- #


def iter_files(root: str, errors: list[ErrorRecord]) -> Iterator[tuple[str, str, os.stat_result]]:
    """递归遍历 root 下的普通文件，产出 (abspath, relpath, stat)。

    安全策略：
      - 目录软链直接跳过（防 symlink 环 / 逃逸），记录到 errors。
      - 文件软链若 realpath 逃出 root，跳过并记录。
      - 单条目错误隔离，不中断整体遍历。
    """
    root_r = _real(root)
    stack: list[str] = [root]
    while stack:
        current = stack.pop()
        try:
            entries = list(os.scandir(current))
        except OSError as exc:
            rel = os.path.relpath(current, root)
            errors.append(ErrorRecord(rel, "scandir", type(exc).__name__, str(exc)[:300]))
            continue
        for entry in entries:
            try:
                is_symlink = entry.is_symlink()
                if entry.is_dir(follow_symlinks=False):
                    if is_symlink:
                        rel = os.path.relpath(entry.path, root)
                        errors.append(
                            ErrorRecord(rel, "walk", "dir_symlink_skipped",
                                        "目录软链已跳过（防逃逸/防环）")
                        )
                        continue
                    stack.append(entry.path)
                    continue
                # 文件（含文件软链）
                if is_symlink and not is_within(entry.path, root_r):
                    rel = os.path.relpath(entry.path, root)
                    errors.append(
                        ErrorRecord(rel, "walk", "symlink_escape_skipped",
                                    "文件软链逃出源根目录，已跳过")
                    )
                    continue
                st = entry.stat(follow_symlinks=False) if is_symlink else entry.stat()
                rel = os.path.relpath(entry.path, root)
                yield entry.path, rel, st
            except OSError as exc:
                rel = os.path.relpath(entry.path, root)
                errors.append(ErrorRecord(rel, "stat", type(exc).__name__, str(exc)[:300]))


# --------------------------------------------------------------------------- #
# 媒体探测（ffprobe，只读）
# --------------------------------------------------------------------------- #


def _to_float(v: object) -> float | None:
    try:
        return float(v) if v is not None else None  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _to_int(v: object) -> int | None:
    try:
        return int(v) if v is not None else None  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _parse_fps(rate: str | None) -> float | None:
    if not rate:
        return None
    try:
        if "/" in rate:
            num, den = rate.split("/", 1)
            den_f = float(den)
            return round(float(num) / den_f, 3) if den_f else None
        return float(rate)
    except (TypeError, ValueError):
        return None


def ffprobe_available(ffprobe_path: str = "ffprobe") -> bool:
    try:
        proc = subprocess.run(  # noqa: S603
            [ffprobe_path, "-version"], capture_output=True, timeout=5, check=False
        )
        return proc.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def probe_media(path: str, *, ffprobe_path: str = "ffprobe", timeout: float = 30.0) -> dict:
    """对单个媒体文件运行 ffprobe，返回结构化 dict。失败时 status=error，绝不抛出。"""
    cmd = [
        ffprobe_path, "-v", "error", "-hide_banner",
        "-print_format", "json", "-show_format", "-show_streams",
        "--", path,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)  # noqa: S603
    except subprocess.TimeoutExpired:
        return {"status": "error", "reason": "timeout"}
    except FileNotFoundError:
        return {"status": "error", "reason": "ffprobe_not_found"}
    except OSError as exc:
        return {"status": "error", "reason": f"os_error:{exc.__class__.__name__}"}

    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", "replace").strip()
        return {"status": "error", "reason": "ffprobe_failed", "detail": stderr[:300]}
    try:
        data = json.loads(proc.stdout.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        return {"status": "error", "reason": "invalid_json"}

    streams = data.get("streams") or []
    fmt = data.get("format") or {}
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video is None:
        return {"status": "error", "reason": "no_video_stream"}

    width = _to_int(video.get("width"))
    height = _to_int(video.get("height"))
    duration = _to_float(fmt.get("duration")) or _to_float(video.get("duration"))
    fps = _parse_fps(video.get("r_frame_rate") or video.get("avg_frame_rate"))

    # 竖拍旋转校正
    rotation = 0
    tags = video.get("tags") or {}
    if "rotate" in tags:
        rotation = _to_int(tags.get("rotate")) or 0
    for side in video.get("side_data_list") or []:
        if "rotation" in side:
            rotation = _to_int(side.get("rotation")) or rotation
    if width and height and abs(rotation) % 180 == 90:
        width, height = height, width

    orientation = None
    if width and height:
        orientation = "landscape" if width > height else "portrait" if height > width else "square"

    return {
        "status": "ok",
        "width": width,
        "height": height,
        "duration": duration,
        "fps": fps,
        "video_codec": video.get("codec_name"),
        "has_audio": audio is not None,
        "orientation": orientation,
    }


# --------------------------------------------------------------------------- #
# 指纹（仅去重候选）
# --------------------------------------------------------------------------- #


def quick_hash(path: str, *, size: int, head_tail: int = QUICK_HASH_BYTES) -> str:
    """头尾各取 head_tail 字节 + 文件大小，计算快速指纹（只读 rb）。非加密用途。"""
    h = hashlib.sha256()
    h.update(str(size).encode())
    with open(path, "rb") as f:
        head = f.read(head_tail)
        h.update(head)
        if size > head_tail * 2:
            f.seek(max(0, size - head_tail))
            h.update(f.read(head_tail))
    return h.hexdigest()


def full_sha256(path: str) -> str:
    """完整 SHA256（只读 rb），仅对 quick-hash 冲突候选调用。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------------------------------- #
# 纯函数：分类 / 产品匹配（便于单测，不触碰文件系统）
# --------------------------------------------------------------------------- #


def kind_of(ext: str, filename: str) -> str:
    name_l = filename.lower()
    ext_l = ext.lower()
    if name_l in JUNK_NAMES or ext_l in JUNK_EXTS:
        return "junk"
    if ext_l in IMAGE_EXTS:
        return "image"
    if ext_l in VIDEO_EXTS:
        return "video"
    if ext_l in SUBTITLE_EXTS:
        return "subtitle"
    if ext_l in EDITOR_PROJECT_EXTS:
        return "editor_project"
    if name_l in {"draft_content.json", "template.json"} or "draft_content" in name_l:
        return "editor_project"
    return "other"


def match_products(text: str) -> list[tuple[str, str | None, str]]:
    """对一段文本（目录/文件名）做产品候选匹配，返回 (family, variant, matched_keyword)。"""
    t = text.lower()
    hits: list[tuple[str, str | None, str]] = []
    seen: set[tuple[str, str | None]] = set()
    for family, variant, keywords in PRODUCT_RULES:
        for kw in keywords:
            if kw.lower() in t:
                key = (family, variant)
                if key not in seen:
                    hits.append((family, variant, kw))
                    seen.add(key)
                break
    return hits


def detect_used_evidence(relpath: str) -> dict | None:
    """检测"已使用 / 成片"历史证据。只判定"可能使用过"，绝不推断使用次数或对应成片。"""
    norm = relpath.replace("\\", "/")
    parts = norm.split("/")
    low = norm.lower()
    matched: list[str] = []
    etype = None
    ambiguous = False

    in_used_dir = any(any(k in p for k in USED_KEYWORDS) for p in parts[:-1])
    in_used_name = any(k in parts[-1] for k in USED_KEYWORDS)
    if in_used_dir or in_used_name:
        etype = "used_dir" if in_used_dir else "used_name"
        matched.extend([k for k in USED_KEYWORDS if k in norm])

    if not matched:
        amb = [k for k in USED_KEYWORDS_AMBIGUOUS if k in low]
        if amb:
            etype = "used_ambiguous"
            matched.extend(amb)
            ambiguous = True

    final_hit = [k for k in FINAL_KEYWORDS if k.lower() in low]
    if final_hit:
        etype = etype or "final_marker"
        matched.extend(final_hit)

    if not matched:
        return None
    return {
        "evidence_type": etype,
        "raw_evidence_text": ";".join(dict.fromkeys(matched)),
        # 业务规则：位于"已使用"目录或带"已使用"只能证明可能曾使用过
        "can_determine_used": "maybe" if not ambiguous else "unknown",
        "can_determine_count": "no",      # 永远不能据此自动判定次数
        "can_determine_final": "no",      # 永远不能据此自动判定对应成片
        "needs_human": True,
    }


def classify_file(rec: FileRecord) -> None:
    """对单条记录做规则分类，原地写入 classification / confidence / evidence / 产品候选。"""
    norm = rec.relpath.replace("\\", "/")
    parts = norm.split("/")
    dirs = parts[:-1]
    name = rec.filename
    evidence: list[str] = []
    needs_human = True
    confidence = "low"

    # 产品候选（目录优先于文件名）
    prod_hits: list[tuple[str, str | None, str]] = []
    for seg in dirs + [name]:
        prod_hits.extend(match_products(seg))
    if prod_hits:
        # 取首个带 variant 的，否则取首个 family
        chosen = next((h for h in prod_hits if h[1]), prod_hits[0])
        rec.product_family, rec.product_variant = chosen[0], chosen[1]
        evidence.append(f"product_keyword:{chosen[2]}")

    has_category = any(any(c in seg.lower() for c in CATEGORY_KEYWORDS) for seg in dirs)
    used = detect_used_evidence(rec.relpath)
    final_markers = [k for k in FINAL_KEYWORDS if k.lower() in norm.lower()]
    in_product_dir = any("产品" in d or "product" in d.lower() for d in dirs)

    # --- 分类决策 ---
    if rec.kind == "junk":
        rec.classification = "system_junk"
        confidence = "high"
        needs_human = False
        evidence.append("junk_file")
    elif rec.kind == "editor_project":
        rec.classification = "editor_project"
        confidence = "high" if rec.ext.lower() != ".xml" else "low"
        needs_human = rec.ext.lower() == ".xml"
        evidence.append(f"editor_project_ext:{rec.ext}")
    elif rec.kind == "subtitle":
        rec.classification = "editor_adjacent"
        confidence = "medium"
        evidence.append("subtitle_file")
    elif rec.kind == "image":
        if in_product_dir or rec.product_family:
            rec.classification = "product_reference_image"
            confidence = "medium"
            evidence.append("image_in_product_context")
        else:
            rec.classification = "unknown"
            evidence.append("image_outside_product_context")
    elif rec.kind == "video":
        if final_markers:
            rec.classification = "final_video_candidate"
            confidence = "low"  # 命名线索不足以确认
            evidence.append(f"final_marker:{','.join(final_markers)}")
        elif used and used["evidence_type"] in {"used_dir", "used_name"}:
            rec.classification = "used_source_candidate"
            confidence = "low"
            evidence.append(f"used_evidence:{used['raw_evidence_text']}")
        elif has_category or rec.product_family:
            rec.classification = "source_video_candidate"
            confidence = "medium" if rec.product_family else "low"
            evidence.append("video_in_shooting_dir")
        else:
            rec.classification = "source_video_candidate"
            confidence = "low"
            evidence.append("video_unscoped")
    else:
        rec.classification = "unknown"
        evidence.append(f"unhandled_ext:{rec.ext}")

    # 体积异常小的视频（疑似代理/压缩/成片）单独提示
    if rec.kind == "video" and rec.size_bytes and rec.size_bytes < 3 * 1024 * 1024:
        evidence.append("very_small_video(<3MB)_maybe_proxy_or_final")
        needs_human = True
    # 低码率视频（疑似代理/重压缩版本）：bitrate = size*8/duration
    if rec.kind == "video" and rec.duration_sec and rec.size_bytes:
        bitrate = rec.size_bytes * 8 / rec.duration_sec
        if bitrate < 1_500_000:
            evidence.append(f"low_bitrate(~{int(bitrate / 1000)}kbps)_maybe_proxy")
            needs_human = True

    rec.classification_confidence = confidence
    rec.evidence = evidence
    rec.needs_human = needs_human


# --------------------------------------------------------------------------- #
# 只读核对（运行前后快照对比）
# --------------------------------------------------------------------------- #


def snapshot(root: str, errors: list[ErrorRecord]) -> dict[str, tuple[int, int]]:
    """返回 {relpath: (size_bytes, mtime_ns)}，用于只读核对。"""
    snap: dict[str, tuple[int, int]] = {}
    for _abs, rel, st in iter_files(root, errors):
        snap[rel] = (st.st_size, st.st_mtime_ns)
    return snap


def compare_snapshots(before: dict, after: dict, sample: int) -> dict:
    """对比前后快照，返回核对报告（不打印完整路径）。"""
    before_keys = set(before)
    after_keys = set(after)
    added = sorted(after_keys - before_keys)
    removed = sorted(before_keys - after_keys)
    changed = [k for k in (before_keys & after_keys) if before[k] != after[k]]
    return {
        "file_count_before": len(before),
        "file_count_after": len(after),
        "added_count": len(added),
        "removed_count": len(removed),
        "changed_count": len(changed),
        "sampled_checked": min(sample, len(before_keys & after_keys)),
        "read_only_ok": not added and not removed and not changed,
        "added_examples": [os.path.basename(p) for p in added[:5]],
        "removed_examples": [os.path.basename(p) for p in removed[:5]],
        "changed_examples": [os.path.basename(p) for p in changed[:5]],
    }


# --------------------------------------------------------------------------- #
# CSV 写入工具
# --------------------------------------------------------------------------- #


def write_csv(path: Path, header: list[str], rows: Iterable[list]) -> int:
    n = 0
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(header)
        for row in rows:
            w.writerow(row)
            n += 1
    return n


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #


def build_inventory(
    root: str,
    *,
    errors: list[ErrorRecord],
    cache: dict,
    output_dir: Path,
    use_ffprobe: bool,
) -> list[FileRecord]:
    records: list[FileRecord] = []
    processed = 0
    for abspath, rel, st in iter_files(root, errors):
        filename = os.path.basename(rel)
        ext = os.path.splitext(filename)[1]
        kind = kind_of(ext, filename)
        rec = FileRecord(
            relpath=rel,
            top_dir=rel.replace("\\", "/").split("/")[0],
            parent_dir=os.path.dirname(rel).replace("\\", "/"),
            filename=filename,
            ext=ext,
            kind=kind,
            size_bytes=st.st_size,
            mtime_ns=st.st_mtime_ns,
            mtime_iso=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime)),
        )
        # 媒体探测（带缓存，支持中断恢复）
        if kind in {"image", "video"} and use_ffprobe:
            cache_key = f"{rel}|{st.st_size}|{st.st_mtime_ns}"
            cached = cache.get(cache_key)
            if cached is None:
                cached = probe_media(abspath)
                cache[cache_key] = cached
                processed += 1
                if processed % CACHE_FLUSH_EVERY == 0:
                    _flush_cache(cache, output_dir)
            probe = cached
            if probe.get("status") == "ok":
                rec.width = probe.get("width")
                rec.height = probe.get("height")
                rec.duration_sec = probe.get("duration")
                rec.fps = probe.get("fps")
                rec.video_codec = probe.get("video_codec")
                rec.has_audio = probe.get("has_audio")
                rec.orientation = probe.get("orientation")
                rec.probe_status = "ok"
            else:
                rec.probe_status = "error"
                rec.error_reason = probe.get("reason", "")
                errors.append(ErrorRecord(rel, "probe", probe.get("reason", "unknown"),
                                          probe.get("detail", "")))
        elif kind in {"image", "video"}:
            rec.probe_status = "skipped"
        else:
            rec.probe_status = "not_media"

        classify_file(rec)
        records.append(rec)
    _flush_cache(cache, output_dir)
    return records


def _cache_path(output_dir: Path) -> Path:
    return output_dir / "_probe_cache.json"


def _load_cache(output_dir: Path) -> dict:
    p = _cache_path(output_dir)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def _flush_cache(cache: dict, output_dir: Path) -> None:
    p = _cache_path(output_dir)
    fd, tmp = tempfile.mkstemp(dir=str(output_dir), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
        os.replace(tmp, p)
    except OSError:
        if os.path.exists(tmp):
            os.unlink(tmp)


def detect_duplicates(
    records: list[FileRecord], errors: list[ErrorRecord], root: str
) -> tuple[list[dict], list[dict]]:
    """分级去重：(size,duration,ext) 候选 → quick hash → 完整 SHA256。

    返回 (duplicate_groups, possible_moves)。
    """
    media = [r for r in records if r.kind in {"image", "video"}]
    # 1) 候选分组
    buckets: dict[tuple, list[FileRecord]] = defaultdict(list)
    for r in media:
        dur = int(round(r.duration_sec)) if r.duration_sec else None
        buckets[(r.kind, r.ext.lower(), r.size_bytes, dur)].append(r)

    dup_groups: list[dict] = []
    possible_moves: list[dict] = []
    gid = 0

    for _bucket_key, group in buckets.items():
        if len(group) < 2:
            continue
        # 2) quick hash
        for r in group:
            try:
                r.quick_hash = quick_hash(os.path.join(root, r.relpath), size=r.size_bytes)
            except OSError as exc:
                errors.append(ErrorRecord(
                    r.relpath, "quick_hash", type(exc).__name__, str(exc)[:200]))
        qbuckets: dict[str, list[FileRecord]] = defaultdict(list)
        for r in group:
            if r.quick_hash:
                qbuckets[r.quick_hash].append(r)
        # 3) 完整 SHA256 仅对 quick-hash 冲突候选
        for _qh, qgroup in qbuckets.items():
            if len(qgroup) < 2:
                continue
            for r in qgroup:
                if r.sha256 is None:
                    try:
                        r.sha256 = full_sha256(os.path.join(root, r.relpath))
                    except OSError as exc:
                        errors.append(ErrorRecord(
                            r.relpath, "sha256", type(exc).__name__, str(exc)[:200]))
            shabuckets: dict[str, list[FileRecord]] = defaultdict(list)
            for r in qgroup:
                if r.sha256:
                    shabuckets[r.sha256].append(r)
            for sha, sgroup in shabuckets.items():
                if len(sgroup) < 2:
                    continue
                gid += 1
                names = {r.filename for r in sgroup}
                top_dirs = {r.top_dir for r in sgroup}
                identity = "exact_same" if len(names) == 1 else "same_content_diff_name"
                dup_groups.append({
                    "group_id": gid,
                    "identity_class": identity,
                    "member_count": len(sgroup),
                    "sha256_prefix": sha[:16],
                    "relpaths": " ; ".join(r.relpath for r in sgroup),
                    "note": "内容完全相同（同一 Asset）" if len(top_dirs) == 1
                            else "内容相同但分布在不同顶层目录（疑似移动/复制）",
                })
                # 移动 / 复制识别
                if len(top_dirs) > 1 or len({r.parent_dir for r in sgroup}) > 1:
                    for i in range(len(sgroup)):
                        for j in range(i + 1, len(sgroup)):
                            a, b = sgroup[i], sgroup[j]
                            a_used = detect_used_evidence(a.relpath) is not None
                            b_used = detect_used_evidence(b.relpath) is not None
                            relation = "possible_move" if (a_used != b_used) else "possible_copy"
                            possible_moves.append({
                                "group_id": gid,
                                "relpath_a": a.relpath,
                                "relpath_b": b.relpath,
                                "relation": relation,
                                "evidence": "same_sha256;diff_location"
                                            + (";one_in_used_dir" if a_used != b_used else ""),
                                "needs_human": "yes",
                            })

    # 注：转码/裁剪/变体（非字节级相同）无法仅凭元数据（大小/时长/分辨率）可靠判定 —
    #    同时长不同分辨率在竖拍/横拍、多机位拍摄中极常见，纯元数据匹配会大量误报。
    #    真正的"内容相同的不同版本"识别需内容指纹（pHash 抽帧 / Chromaprint 音频），
    #    属后续能力（见 OPEN_SOURCE_REUSE_EVALUATION 与路线图）。本阶段只输出
    #    哈希确认的精确重复/移动/复制，转码/裁剪一律标记为"无法仅凭元数据确定"。
    return dup_groups, possible_moves


def build_product_catalog(records: list[FileRecord]) -> tuple[list[dict], list[dict], list[dict]]:
    """产品目录 / 别名 / 评审队列草案。"""
    fam_stats: dict[tuple[str, str | None], dict] = defaultdict(
        lambda: {"images": 0, "videos": 0, "folders": set(), "keywords": set()}
    )
    alias_examples: dict[tuple[str, str, str], set] = defaultdict(set)

    for r in records:
        if r.product_family is None:
            continue
        key = (r.product_family, r.product_variant)
        if r.kind == "image":
            fam_stats[key]["images"] += 1
        elif r.kind == "video":
            fam_stats[key]["videos"] += 1
        fam_stats[key]["folders"].add(r.parent_dir.split("/")[-1] if r.parent_dir else "")
        for ev in r.evidence:
            if ev.startswith("product_keyword:"):
                kw = ev.split(":", 1)[1]
                fam_stats[key]["keywords"].add(kw)
                # 别名来源：关键词 → 产品族/变体
                alias_examples[(kw, "keyword", r.product_family)].add(r.product_variant or "")

    name_en = {
        "恶魔之眼": "demon eye light",
        "车换挡握把": "gear shift knob",
        "小键盘": "mini keyboard",
    }
    confusable = {
        ("恶魔之眼", "软屏"): "恶魔之眼/硬屏",
        ("恶魔之眼", "硬屏"): "恶魔之眼/软屏",
    }

    catalog: list[dict] = []
    for (family, variant), s in sorted(fam_stats.items(), key=lambda x: (x[0][0], x[0][1] or "")):
        is_variant_known = variant is not None
        catalog.append({
            "product_family": family,
            "product_variant": variant or "(未细分)",
            "sku_candidate": "",
            "name_cn": f"{family}{variant or ''}",
            "name_en_candidate": name_en.get(family, ""),
            "aliases": " ; ".join(sorted(s["keywords"])),
            "folder_aliases": " ; ".join(sorted(x for x in s["folders"] if x)),
            "ref_image_count": s["images"],
            "video_count": s["videos"],
            "confusable_with": confusable.get((family, variant), ""),
            "visible_features": "（待人工补充）" if not is_variant_known else "",
            "confidence": "medium" if is_variant_known else "low",
            "open_questions": "需人工确认变体与 SKU 绑定"
                              + ("；软屏/硬屏差异特征待补" if family == "恶魔之眼" else ""),
            "needs_human": "yes",
        })

    alias_rows: list[dict] = []
    seen_alias: set = set()
    for (kw, atype, family), variants in alias_examples.items():
        k = (kw, family)
        if k in seen_alias:
            continue
        seen_alias.add(k)
        alias_rows.append({
            "alias_text": kw,
            "alias_type": atype,
            "maps_to_family": family,
            "maps_to_variant": " / ".join(sorted(v for v in variants if v)) or "",
            "confidence": "medium",
            "evidence_examples": "出现在目录/文件名关键词",
            "needs_human": "yes",
        })

    # 评审队列：软屏 vs 硬屏 差异 + 品类→产品绑定
    review: list[dict] = []
    for q in SOFT_VS_HARD_QUESTIONS:
        review.append({
            "topic": "恶魔之眼软屏 vs 硬屏 区分",
            "product_family": "恶魔之眼",
            "product_variant": "软屏/硬屏",
            "question": q,
            "why": "目录名无法可靠区分软/硬屏，需人工提供可见识别特征",
            "suggested_human_action": "运营提供对照图或文字说明",
            "priority": "high",
        })
    review.append({
        "topic": "拍摄品类→具体产品绑定",
        "product_family": "(汽配/数码等品类)",
        "product_variant": "",
        "question": "汽配/数码/素材 等日期目录分别对应哪个具体产品？",
        "why": "目录名仅表示拍摄品类与日期，不能据此最终确认产品身份",
        "suggested_human_action": "运营按目录提供产品归属",
        "priority": "high",
    })
    return catalog, alias_rows, review


def build_benchmark_seeds(records: list[FileRecord]) -> dict[str, list[dict]]:
    """从真实数据生成评测种子候选与标注模板（不伪造人工真值）。"""
    seeds: list[dict] = []
    sid = 0
    # 产品识别种子：每个产品参考图
    for r in records:
        if r.classification == "product_reference_image":
            sid += 1
            seeds.append({
                "benchmark_type": "product_id",
                "seed_id": f"PID-{sid:04d}",
                "scope": r.parent_dir,
                "candidate_input": r.filename,
                "expected_note": (
                    f"family={r.product_family or '?'};"
                    f"variant={r.product_variant or '?'}"
                ),
                "needs_human_truth": "yes",
            })
    # 检索种子：每个源视频候选
    for r in records:
        if r.classification == "source_video_candidate":
            sid += 1
            seeds.append({
                "benchmark_type": "search",
                "seed_id": f"SR-{sid:04d}",
                "scope": r.top_dir,
                "candidate_input": r.filename,
                "expected_note": f"product={r.product_family or '?'};dur={r.duration_sec}",
                "needs_human_truth": "yes",
            })

    query_template = [{
        "query_id": "Q-0001",
        "natural_language_query": "（示例）恶魔之眼软屏 安装在车内 近景特写",
        "product_family": "恶魔之眼",
        "product_variant": "软屏",
        "action": "安装",
        "scene": "车内",
        "shot_size": "近景",
        "must_include": "产品清晰",
        "must_exclude": "他款产品",
        "relevant_relpaths": "",
        "notes": "人工填写真值",
    }]
    lineage_template = [{
        "final_video_relpath": "",
        "source_asset_relpath": "",
        "source_shot_timecode": "",
        "evidence_level": "confirmed_manual",
        "confirmed": "",
        "notes": "人工填写：成片→源镜头引用关系",
    }]
    storyboard_template = [{
        "storyboard_id": "SB-0001",
        "segment_index": "1",
        "product": "恶魔之眼",
        "product_variant": "软屏",
        "action": "产品展示",
        "scene": "桌面",
        "shot_size": "特写",
        "camera_move": "推",
        "target_duration_sec": "3",
        "must_include": "产品正面",
        "must_exclude": "包装盒",
        "aspect_ratio": "9:16",
        "risk": "无",
        "usage_policy": "优先未使用",
        "chosen_relpath": "",
        "notes": "人工填写理想镜头",
    }]
    return {
        "benchmark_seed_candidates": seeds,
        "query_labeling_template": query_template,
        "usage_lineage_labeling_template": lineage_template,
        "storyboard_labeling_template": storyboard_template,
    }


# --------------------------------------------------------------------------- #
# 输出
# --------------------------------------------------------------------------- #


def emit_outputs(
    output_dir: Path,
    records: list[FileRecord],
    errors: list[ErrorRecord],
    dup_groups: list[dict],
    possible_moves: list[dict],
    catalog: list[dict],
    aliases: list[dict],
    review_products: list[dict],
    benchmark: dict[str, list[dict]],
    readonly_report: dict,
    root_display: str,
    root_fingerprint: str,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)

    # inventory.csv
    inv_header = [
        "relpath", "top_dir", "parent_dir", "filename", "ext", "kind",
        "size_bytes", "size_mb", "mtime_iso", "width", "height", "duration_sec",
        "fps", "video_codec", "has_audio", "orientation",
        "product_family", "product_variant",
        "classification", "classification_confidence", "inference_type",
        "evidence", "needs_human", "probe_status", "error_reason",
    ]
    write_csv(output_dir / "inventory.csv", inv_header, (
        [
            r.relpath, r.top_dir, r.parent_dir, r.filename, r.ext, r.kind,
            r.size_bytes, round(r.size_bytes / 1048576, 2), r.mtime_iso,
            r.width, r.height, round(r.duration_sec, 2) if r.duration_sec else "",
            r.fps, r.video_codec, r.has_audio, r.orientation,
            r.product_family or "", r.product_variant or "",
            r.classification, r.classification_confidence, r.inference_type,
            " | ".join(r.evidence), "yes" if r.needs_human else "no",
            r.probe_status, r.error_reason,
        ]
        for r in records
    ))

    # 分类子集
    src = [r for r in records if r.classification == "source_video_candidate"]
    fin = [r for r in records if r.classification == "final_video_candidate"]
    unk = [r for r in records if r.classification == "unknown"]

    write_csv(output_dir / "source_video_candidates.csv",
              ["relpath", "top_dir", "duration_sec", "width", "height", "has_audio",
               "size_mb", "product_family_candidate", "confidence", "evidence", "needs_human"],
              ([r.relpath, r.top_dir, round(r.duration_sec, 2) if r.duration_sec else "",
                r.width, r.height, r.has_audio, round(r.size_bytes / 1048576, 2),
                r.product_family or "", r.classification_confidence,
                " | ".join(r.evidence), "yes" if r.needs_human else "no"] for r in src))

    write_csv(output_dir / "final_video_candidates.csv",
              ["relpath", "top_dir", "duration_sec", "width", "height", "has_audio",
               "size_mb", "final_evidence", "confidence", "needs_human"],
              ([r.relpath, r.top_dir, round(r.duration_sec, 2) if r.duration_sec else "",
                r.width, r.height, r.has_audio, round(r.size_bytes / 1048576, 2),
                " | ".join(r.evidence), r.classification_confidence,
                "yes" if r.needs_human else "no"] for r in fin))

    write_csv(output_dir / "unknown_media.csv",
              ["relpath", "kind", "ext", "size_mb", "reason", "needs_human"],
              ([r.relpath, r.kind, r.ext, round(r.size_bytes / 1048576, 2),
                " | ".join(r.evidence), "yes" if r.needs_human else "no"] for r in unk))

    # used_evidence.csv
    used_rows = []
    for r in records:
        ue = detect_used_evidence(r.relpath)
        if ue:
            used_rows.append([
                r.relpath, ue["evidence_type"], ue["raw_evidence_text"],
                ue["can_determine_used"], ue["can_determine_count"],
                ue["can_determine_final"], "yes" if ue["needs_human"] else "no",
                "位于已使用目录/带已使用后缀只能证明可能曾使用，不能据此判定次数或对应成片",
            ])
    write_csv(output_dir / "used_evidence.csv",
              ["relpath", "evidence_type", "raw_evidence_text", "can_determine_used",
               "can_determine_count", "can_determine_final", "needs_human", "note"],
              used_rows)

    # 去重 / 移动
    write_csv(output_dir / "duplicate_groups.csv",
              ["group_id", "identity_class", "member_count", "sha256_prefix", "relpaths", "note"],
              ([g["group_id"], g["identity_class"], g["member_count"], g["sha256_prefix"],
                g["relpaths"], g["note"]] for g in dup_groups))
    write_csv(output_dir / "possible_moves.csv",
              ["group_id", "relpath_a", "relpath_b", "relation", "evidence", "needs_human"],
              ([m["group_id"], m["relpath_a"], m["relpath_b"], m["relation"],
                m["evidence"], m["needs_human"]] for m in possible_moves))

    # 产品草案
    write_csv(output_dir / "product_catalog_draft.csv",
              ["product_family", "product_variant", "sku_candidate", "name_cn",
               "name_en_candidate", "aliases", "folder_aliases", "ref_image_count",
               "video_count", "confusable_with", "visible_features", "confidence",
               "open_questions", "needs_human"],
              ([c[k] for k in ["product_family", "product_variant", "sku_candidate",
                               "name_cn", "name_en_candidate", "aliases", "folder_aliases",
                               "ref_image_count", "video_count", "confusable_with",
                               "visible_features", "confidence", "open_questions",
                               "needs_human"]] for c in catalog))
    write_csv(output_dir / "product_alias_draft.csv",
              ["alias_text", "alias_type", "maps_to_family", "maps_to_variant",
               "confidence", "evidence_examples", "needs_human"],
              ([a[k] for k in ["alias_text", "alias_type", "maps_to_family",
                               "maps_to_variant", "confidence", "evidence_examples",
                               "needs_human"]] for a in aliases))
    write_csv(output_dir / "product_review_queue.csv",
              ["topic", "product_family", "product_variant", "question", "why",
               "suggested_human_action", "priority"],
              ([r[k] for k in ["topic", "product_family", "product_variant", "question",
                               "why", "suggested_human_action", "priority"]]
               for r in review_products))

    # errors.csv
    write_csv(output_dir / "errors.csv",
              ["relpath", "stage", "error_reason", "detail"],
              ([e.relpath, e.stage, e.error_reason, e.detail] for e in errors))

    # 评测种子 + 模板
    bsc = benchmark["benchmark_seed_candidates"]
    write_csv(output_dir / "benchmark_seed_candidates.csv",
              ["benchmark_type", "seed_id", "scope", "candidate_input",
               "expected_note", "needs_human_truth"],
              ([b[k] for k in ["benchmark_type", "seed_id", "scope", "candidate_input",
                               "expected_note", "needs_human_truth"]] for b in bsc))
    qt = benchmark["query_labeling_template"]
    write_csv(output_dir / "query_labeling_template.csv", list(qt[0].keys()),
              ([row[k] for k in row] for row in qt))
    lt = benchmark["usage_lineage_labeling_template"]
    write_csv(output_dir / "usage_lineage_labeling_template.csv", list(lt[0].keys()),
              ([row[k] for k in row] for row in lt))
    st = benchmark["storyboard_labeling_template"]
    write_csv(output_dir / "storyboard_labeling_template.csv", list(st[0].keys()),
              ([row[k] for k in row] for row in st))

    # 汇总人工评审队列（聚合最关键的人工确认项）
    rq_rows = []
    rid = 0
    for r in review_products:
        rid += 1
        rq_rows.append([f"RQ-{rid:04d}", "product", r["product_variant"] or r["product_family"],
                        r["question"], r["why"], r["suggested_human_action"], r["priority"]])
    for g in dup_groups:
        rid += 1
        rq_rows.append([f"RQ-{rid:04d}", "duplicate", f"group {g['group_id']}",
                        "确认是否同一 Asset / 是否为移动或复制",
                        g["note"], "运营/素材管理员确认", "medium"])
    for r in (x for x in records if x.classification == "final_video_candidate"):
        rid += 1
        rq_rows.append([f"RQ-{rid:04d}", "final_video", r.top_dir,
                        "确认该视频是否最终成片", " | ".join(r.evidence),
                        "剪辑/运营确认", "medium"])
    write_csv(output_dir / "review_queue.csv",
              ["item_id", "category", "scope", "question", "why", "suggested_action", "priority"],
              rq_rows)

    # 统计汇总
    summary = compute_summary(records, errors, dup_groups, possible_moves, catalog,
                              readonly_report, root_display, root_fingerprint, used_rows)
    (output_dir / "audit_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "audit_summary.md").write_text(
        render_summary_md(summary), encoding="utf-8")
    return summary


def compute_summary(records, errors, dup_groups, possible_moves, catalog,
                    readonly_report, root_display, root_fingerprint, used_rows) -> dict:
    by_kind = defaultdict(int)
    by_class = defaultdict(int)
    by_topdir = defaultdict(lambda: {"files": 0, "size_bytes": 0, "videos": 0, "images": 0})
    total_size = 0
    for r in records:
        by_kind[r.kind] += 1
        by_class[r.classification] += 1
        total_size += r.size_bytes
        td = by_topdir[r.top_dir]
        td["files"] += 1
        td["size_bytes"] += r.size_bytes
        if r.kind == "video":
            td["videos"] += 1
        elif r.kind == "image":
            td["images"] += 1

    can_count = sum(1 for u in used_rows if u[4] == "yes")  # can_determine_count == yes
    can_final = sum(1 for u in used_rows if u[5] == "yes")  # can_determine_final == yes
    proxy_candidates = sum(
        1 for r in records
        if any("low_bitrate" in e or "very_small_video" in e for e in r.evidence)
    )
    return {
        "proxy_candidate_count": proxy_candidates,
        "root_display": root_display,
        "root_fingerprint": root_fingerprint,
        "total_files": len(records),
        "total_size_bytes": total_size,
        "total_size_gb": round(total_size / 1073741824, 3),
        "by_kind": dict(by_kind),
        "by_classification": dict(by_class),
        "by_top_dir": {k: {**v, "size_gb": round(v["size_bytes"] / 1073741824, 3)}
                       for k, v in sorted(by_topdir.items())},
        "image_count": by_kind.get("image", 0),
        "video_count": by_kind.get("video", 0),
        "other_count": sum(v for k, v in by_kind.items() if k not in {"image", "video"}),
        "product_candidate_count": len(catalog),
        "source_video_candidate_count": by_class.get("source_video_candidate", 0),
        "final_video_candidate_count": by_class.get("final_video_candidate", 0),
        "used_evidence_count": len(used_rows),
        "used_evidence_can_determine_count": can_count,
        "used_evidence_can_determine_final": can_final,
        "duplicate_group_count": len(dup_groups),
        "possible_move_count": len(possible_moves),
        "unknown_media_count": by_class.get("unknown", 0),
        "error_count": len(errors),
        "readonly_verification": readonly_report,
        "evidence_layers": {
            "facts": "文件 stat + ffprobe 媒体信息",
            "rule_inference": "基于目录/文件名/后缀/时长/分辨率的候选分类",
            "ai_inference": "未在本阶段进行",
            "human_confirmed": "未在本阶段进行",
        },
    }


def render_summary_md(s: dict) -> str:
    ro = s["readonly_verification"]
    ro_added = ro.get("added_count")
    ro_removed = ro.get("removed_count")
    ro_changed = ro.get("changed_count")
    dup_n = s["duplicate_group_count"]
    move_n = s["possible_move_count"]
    proxy_n = s.get("proxy_candidate_count", 0)
    lines = [
        "# 素材库只读盘点汇总（Phase 0 / Discovery）",
        "",
        f"- 扫描对象：`{s['root_display']}`（指纹 `{s['root_fingerprint']}`）",
        f"- 只读核对：**{'通过 ✅' if ro.get('read_only_ok') else '未通过 ❌'}** "
        f"(前 {ro.get('file_count_before')} / 后 {ro.get('file_count_after')} 文件，"
        f"新增 {ro_added} / 删除 {ro_removed} / 变更 {ro_changed})",
        "",
        "## 1. 关键回答（§10 十五问）",
        "",
        f"1. 共多少文件：**{s['total_files']}**（总体积 {s['total_size_gb']} GB）",
        f"2. 共多少图片：**{s['image_count']}**",
        f"3. 共多少视频：**{s['video_count']}**",
        f"4. 共多少产品候选：**{s['product_candidate_count']}**（family×variant 维度）",
        f"5. 共多少疑似原素材：**{s['source_video_candidate_count']}**",
        f"6. 共多少疑似成片：**{s['final_video_candidate_count']}**",
        f"7. 共多少“已使用”证据：**{s['used_evidence_count']}**",
        f"8. 能确定使用次数的数量：**{s['used_evidence_can_determine_count']}**"
        "（业务规则：目录/后缀证据不能确定次数）",
        f"9. 能确定对应成片的数量：**{s['used_evidence_can_determine_final']}**"
        "（业务规则：不能据路径反查成片引用）",
        f"10. 共多少重复组：**{dup_n}**（疑似移动/复制 {move_n} 对）",
        f"11. 共多少未知文件：**{s['unknown_media_count']}**",
        "12. 当前最明显的数据问题：见下方“数据问题”",
        "13. 哪些需要运营人工确认：见 `product_review_queue.csv` 与 `review_queue.csv`",
        "14. 是否足以建立第一版评测集：**可建立种子集**，但人工真值需运营标注",
        "15. 下一阶段缺少哪些信息：见下方“信息缺口”",
        "",
        "## 2. 各顶层目录",
        "",
        "| 顶层目录 | 文件 | 视频 | 图片 | 体积(GB) |",
        "|---|---|---|---|---|",
    ]
    for td, v in s["by_top_dir"].items():
        lines.append(f"| {td} | {v['files']} | {v['videos']} | {v['images']} | {v['size_gb']} |")
    lines += [
        "",
        "## 3. 分类分布（规则推断，均为候选）",
        "",
        "| 分类 | 数量 |",
        "|---|---|",
    ]
    for k, v in sorted(s["by_classification"].items(), key=lambda x: -x[1]):
        lines.append(f"| {k} | {v} |")
    lines += [
        "",
        "## 4. 证据分层声明",
        "",
        "- **事实**：文件 stat + ffprobe 媒体信息。",
        "- **规则推断**：基于目录/文件名/后缀/时长/分辨率的候选分类（全部 needs_human）。",
        "- **AI 推断 / 人工确认**：本阶段不进行，留待后续 PR。",
        "",
        "## 5. 数据问题（最明显）",
        "",
        "- 产品归属依赖目录名与文件名，软屏/硬屏无法据目录名可靠区分。",
        "- “已使用”仅以目录/后缀体现，无法得到使用次数与成片引用；"
        f"本库 {dup_n} 个字节级重复组，说明“已使用”很可能靠**移动**而非复制。",
        f"- 疑似低码率/代理视频 {proxy_n} 个（如 20250829-素材 整体偏小）。",
        "- 转码/裁剪/变体（非字节相同）无法仅凭元数据判定，"
        "需内容指纹（pHash/Chromaprint），属后续能力。",
        "- 存在系统垃圾文件（Thumbs.db/.DS_Store 等）。",
        "",
        "## 6. 信息缺口（下一阶段需要）",
        "",
        "- 产品 SKU 与变体的人工台账（尤其软屏 vs 硬屏差异特征）。",
        "- 成片与源镜头的真实引用关系（需剪辑工程或人工标注）。",
        "- 检索/分镜评测的人工真值标注。",
        "",
        "> 注：本文件位于 `.local/`，不提交 Git；不含完整绝对路径。",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #


def run_audit(root: str, output: str, *, verify_sample: int = DEFAULT_VERIFY_SAMPLE) -> int:
    if not os.path.isdir(root):
        print(f"[FATAL] 源根目录不存在或不可读，安全退出：{root}", file=sys.stderr)
        return 2
    output_dir = Path(output)
    assert_output_safe(root, str(output_dir))
    output_dir.mkdir(parents=True, exist_ok=True)

    root_display = os.path.basename(os.path.normpath(root)) or root
    root_fingerprint = hashlib.sha256(_real(root).encode("utf-8")).hexdigest()[:12]

    errors: list[ErrorRecord] = []
    use_ffprobe = ffprobe_available()
    if not use_ffprobe:
        print("[WARN] 未检测到 ffprobe，媒体维度/时长将缺失（分类仍可进行）。", file=sys.stderr)

    # 运行前只读快照
    before = snapshot(root, errors)

    cache = _load_cache(output_dir)
    records = build_inventory(root, errors=errors, cache=cache,
                              output_dir=output_dir, use_ffprobe=use_ffprobe)
    dup_groups, possible_moves = detect_duplicates(records, errors, root)
    catalog, aliases, review_products = build_product_catalog(records)
    benchmark = build_benchmark_seeds(records)

    # 运行后只读快照 + 核对
    after = snapshot(root, errors)
    readonly_report = compare_snapshots(before, after, verify_sample)

    summary = emit_outputs(
        output_dir, records, errors, dup_groups, possible_moves,
        catalog, aliases, review_products, benchmark,
        readonly_report, root_display, root_fingerprint,
    )

    ro_ok = readonly_report["read_only_ok"]
    print(f"[OK] 盘点完成：{summary['total_files']} 文件 / "
          f"{summary['video_count']} 视频 / {summary['image_count']} 图片 / "
          f"{summary['total_size_gb']} GB")
    print(f"[{'OK' if ro_ok else 'FAIL'}] 只读核对："
          f"{'源目录全程未变化' if ro_ok else '检测到源目录变化，请人工排查'}")
    print(f"[OK] 输出目录：{output_dir}")
    return 0 if ro_ok else 3


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="ClipMind 素材库只读盘点（Phase 0 Discovery）。脚本不修改任何源文件。"
    )
    parser.add_argument("--root", required=True, help="素材根目录（只读扫描）")
    parser.add_argument("--output", required=True, help="输出目录（应为被 git 忽略的 .local/...）")
    parser.add_argument("--verify-sample", type=int, default=DEFAULT_VERIFY_SAMPLE,
                        help="只读核对抽样数量（默认 %(default)s）")
    args = parser.parse_args(argv)
    return run_audit(args.root, args.output, verify_sample=args.verify_sample)


if __name__ == "__main__":
    raise SystemExit(main())
