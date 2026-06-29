"""派生文件目录布局、磁盘预检、原子移动与清理。

目录布局（data_dir 下）：
  assets/{asset_id}/active/shots/{shot_id}/{keyframe.webp,thumbnail.webp,proxy.mp4}
  assets/{asset_id}/runs/{run_uuid}/staging/shot_{seq:04d}/...
  exports/{export_uuid}/{safe_name}.mp4

安全：
- 一切路径经 safe_join_within_root 校验，确保落在 data_dir 之内（防穿越）。
- 源目录只读；这里只写 data_dir。
- 临时 staging 与 active 同一文件系统，保证 os.replace 原子重命名可用。
"""

from __future__ import annotations

import os
import shutil

from clipmind_shared.security import safe_join_within_root


class DiskSpaceError(Exception):
    """data_dir 可用空间不足。"""


def data_root(data_dir: str) -> str:
    """确保 data_dir 存在并返回其 realpath。"""
    os.makedirs(data_dir, exist_ok=True)
    return os.path.realpath(data_dir)


def _join(root_real: str, *parts: str) -> str:
    return safe_join_within_root(root_real, *parts)


def asset_dir(root_real: str, asset_id: int) -> str:
    return _join(root_real, "assets", str(int(asset_id)))


def active_dir(root_real: str, asset_id: int) -> str:
    return _join(root_real, "assets", str(int(asset_id)), "active")


def active_shot_dir(root_real: str, asset_id: int, shot_id: int) -> str:
    return _join(root_real, "assets", str(int(asset_id)), "active", "shots", str(int(shot_id)))


def run_dir(root_real: str, asset_id: int, run_uuid: str) -> str:
    return _join(root_real, "assets", str(int(asset_id)), "runs", run_uuid)


def run_staging_dir(root_real: str, asset_id: int, run_uuid: str) -> str:
    return _join(root_real, "assets", str(int(asset_id)), "runs", run_uuid, "staging")


def runs_dir(root_real: str, asset_id: int) -> str:
    return _join(root_real, "assets", str(int(asset_id)), "runs")


def export_dir(root_real: str, export_uuid: str) -> str:
    return _join(root_real, "exports", export_uuid)


def script_export_dir(root_real: str, export_uuid: str) -> str:
    """脚本剪辑清单 CSV 导出目录（与片段视频导出 exports/ 分离）。"""
    return _join(root_real, "script_exports", export_uuid)


def bundle_export_dir(root_real: str, export_uuid: str) -> str:
    """多镜头 ZIP 打包导出目录（PR-06B，与 exports/ / script_exports/ 分离）。"""
    return _join(root_real, "bundle_exports", export_uuid)


def ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


def relpath(root_real: str, abspath: str) -> str:
    """返回相对 data_dir 的 POSIX 相对路径（存库用，绝不存绝对路径）。"""
    rel = os.path.relpath(abspath, root_real)
    return rel.replace(os.sep, "/")


def check_disk_space(root_real: str, min_free_mb: int) -> None:
    usage = shutil.disk_usage(root_real)
    free_mb = usage.free / (1024 * 1024)
    if free_mb < min_free_mb:
        raise DiskSpaceError(
            f"data_dir 可用空间不足：剩余 {free_mb:.0f}MiB < 要求 {min_free_mb}MiB"
        )


def atomic_move(src: str, dst: str) -> None:
    """同一文件系统内原子重命名（覆盖目标）。"""
    ensure_dir(os.path.dirname(dst))
    os.replace(src, dst)


def move_dir_contents(src_dir: str, dst_dir: str) -> None:
    """把 src_dir 下的文件逐个原子移动到 dst_dir。"""
    ensure_dir(dst_dir)
    for name in os.listdir(src_dir):
        atomic_move(os.path.join(src_dir, name), os.path.join(dst_dir, name))


def remove_path(path: str) -> None:
    """安全删除文件或目录（忽略不存在）。"""
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)
    elif os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass
