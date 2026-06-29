"""PR-06B media-worker：多镜头 ZIP 打包导出（media 队列）。

按 PRD §7.15.2：对多个真实 Shot 各自从源视频裁剪 clip → 打包 ZIP，内含：
  clips/NNN_*.mp4 + manifest.json + edit-list.csv + README.txt

安全：源目录只读、经白名单根 + safe_join 校验；输出只写 data_dir 的 bundle_exports/{uuid}/；
manifest/清单**绝不含**本机绝对路径 / 源路径 / Key / Endpoint。失败可重试（acks_late），
COMPLETED 须 ZIP 落盘；任一片段失败不静默成功（无可用片段则整体 FAILED）。
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import zipfile
from typing import Any

from clipmind_shared.constants import ERROR_MESSAGE_MAX_LEN, TASK_EXPORT_BUNDLE
from clipmind_shared.db.base import utcnow
from clipmind_shared.ffprobe import ProbeError, probe_video
from clipmind_shared.models import (
    Asset,
    AssetProduct,
    BundleExport,
    Product,
    Shot,
    ShotTag,
    SourceDirectory,
    Tag,
)
from clipmind_shared.models.enums import ExportStatus, ShotStatus, TagType
from clipmind_shared.script.editlist import _guard
from clipmind_shared.security import resolve_and_validate_root, safe_join_within_root
from sqlalchemy import select
from sqlalchemy.orm import Session

from clipmind_worker.celery_app import celery_app
from clipmind_worker.config import get_settings
from clipmind_worker.db import SessionLocal
from clipmind_worker.media import ffmpeg, storage

logger = logging.getLogger(__name__)

_UNSAFE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_README = (
    "ClipMind 镜头打包导出\n"
    "====================\n\n"
    "clips/        各镜头从源视频按时间码裁剪的片段（顺序即所选顺序）。\n"
    "manifest.json 每个片段的来源信息：镜头/素材 id、源入出点、时长、场景/动作/产品、项目。\n"
    "edit-list.csv 剪辑清单（一行一段，便于核对）。\n\n"
    "本包不含源视频原文件、不含任何本机绝对路径或凭据。\n"
)


def _truncate(text: str) -> str:
    return text[:ERROR_MESSAGE_MAX_LEN]


def _clip_name(seq: int, source_filename: str, start: float, end: float) -> str:
    stem = _UNSAFE.sub("_", os.path.splitext(source_filename or "clip")[0])[:60]

    def mmss(x: float) -> str:
        return f"{int(x // 60):02d}m{int(x % 60):02d}s"

    return f"{seq:03d}_{stem}_{mmss(start)}-{mmss(end)}.mp4"


def _shot_tag_names(session: Session, shot_id: int, tag_type: TagType) -> list[str]:
    rows = session.execute(
        select(Tag.tag_name)
        .select_from(ShotTag)
        .join(Tag, Tag.id == ShotTag.tag_id)
        .where(ShotTag.shot_id == shot_id, ShotTag.active.is_(True), Tag.tag_type == tag_type)
    ).scalars().all()
    return list(dict.fromkeys(rows))


def _asset_products(session: Session, asset_id: int) -> list[str]:
    rows = session.execute(
        select(Product.name)
        .select_from(AssetProduct)
        .join(Product, Product.id == AssetProduct.product_id)
        .where(AssetProduct.asset_id == asset_id)
    ).scalars().all()
    return list(dict.fromkeys(rows))


def _build_edit_list_csv(entries: list[dict]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(
        ["序号", "镜头ID", "素材ID", "源入点(s)", "源出点(s)", "时长(s)",
         "文件名", "场景", "动作", "产品"]
    )
    for e in entries:
        writer.writerow([
            e["index"], e["shot_id"], e["asset_id"],
            f"{e['source_start']:.3f}", f"{e['source_end']:.3f}", f"{e['duration']:.3f}",
            _guard(e["exported_filename"]),
            _guard("、".join(e["scenes"])), _guard("、".join(e["actions"])),
            _guard("、".join(e["products"])),
        ])
    return b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")


@celery_app.task(name=TASK_EXPORT_BUNDLE, bind=True, acks_late=True)
def export_bundle(self, export_id: int) -> dict[str, Any]:  # noqa: ANN001
    settings = get_settings()
    with SessionLocal() as session:
        bundle = session.get(BundleExport, export_id)
        if bundle is None:
            return {"error": "bundle_not_found", "export_id": export_id}
        if bundle.status != ExportStatus.QUEUED:
            return {"skipped": True, "reason": f"status={bundle.status.value}"}

        bundle.status = ExportStatus.RUNNING
        bundle.started_at = utcnow()
        session.commit()

        try:
            root = storage.data_root(settings.data_dir)
            storage.check_disk_space(root, settings.disk_min_free_mb)
            bdir = storage.bundle_export_dir(root, bundle.export_uuid)
            clips_dir = storage.ensure_dir(os.path.join(bdir, "clips"))

            shot_ids = [int(s) for s in (bundle.shot_ids or [])]
            entries: list[dict] = []
            for seq, shot_id in enumerate(shot_ids, start=1):
                shot = session.get(Shot, shot_id)
                if shot is None or shot.status != ShotStatus.READY:
                    continue  # 跳过不存在/未就绪镜头（不静默成功——下方校验 entries 非空）
                asset = session.get(Asset, shot.asset_id)
                if asset is None:
                    continue
                sd = session.get(SourceDirectory, asset.source_directory_id)
                if sd is None:
                    continue
                src_root = resolve_and_validate_root(sd.mount_path, settings.allowed_roots_list)
                src_abs = safe_join_within_root(src_root, asset.relative_path)
                if not os.path.isfile(src_abs):
                    continue

                clip_name = _clip_name(seq, asset.filename, shot.start_time, shot.end_time)
                out_abs = os.path.join(clips_dir, clip_name)
                try:
                    has_audio = probe_video(src_abs, timeout=settings.ffprobe_timeout).has_audio
                except ProbeError:
                    has_audio = False
                ffmpeg.export_clip(
                    src_abs, shot.start_time, shot.end_time, out_abs,
                    mode=bundle.mode, has_audio=has_audio, timeout=settings.ffmpeg_timeout,
                )
                ffmpeg.validate_media(out_abs, ffprobe_timeout=settings.ffprobe_timeout)

                entries.append({
                    "index": seq,
                    "shot_id": shot.id,
                    "asset_id": asset.id,
                    "sequence_no": shot.sequence_no,
                    "source_start": float(shot.start_time),
                    "source_end": float(shot.end_time),
                    "duration": round(float(shot.end_time - shot.start_time), 3),
                    "exported_filename": clip_name,
                    "scenes": _shot_tag_names(session, shot.id, TagType.SCENE),
                    "actions": _shot_tag_names(session, shot.id, TagType.ACTION),
                    "products": _asset_products(session, asset.id),
                })

            if not entries:
                raise ValueError("no_valid_shots_to_bundle")

            manifest = {
                "kind": "shot_bundle",
                "schema_version": 1,
                "project_id": bundle.project_id,
                "generated_at": utcnow().isoformat(),
                "clip_count": len(entries),
                "clips": entries,
            }
            manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
            editlist_bytes = _build_edit_list_csv(entries)

            with open(os.path.join(bdir, "manifest.json"), "wb") as f:
                f.write(manifest_bytes)
            with open(os.path.join(bdir, "edit-list.csv"), "wb") as f:
                f.write(editlist_bytes)
            with open(os.path.join(bdir, "README.txt"), "w", encoding="utf-8") as f:
                f.write(_README)

            # 打包 ZIP（clips/ + manifest + edit-list + README）
            zip_abs = os.path.join(bdir, "bundle.zip")
            with zipfile.ZipFile(zip_abs, "w", zipfile.ZIP_DEFLATED) as zf:
                for e in entries:
                    zf.write(os.path.join(clips_dir, e["exported_filename"]),
                             arcname=f"clips/{e['exported_filename']}")
                zf.writestr("manifest.json", manifest_bytes)
                zf.writestr("edit-list.csv", editlist_bytes)
                zf.writestr("README.txt", _README)

            bundle.output_path = storage.relpath(root, zip_abs)
            bundle.filename = f"镜头打包_{len(entries)}个片段.zip"
            bundle.row_count = len(entries)
            bundle.status = ExportStatus.COMPLETED
            bundle.finished_at = utcnow()
            session.commit()
            return {"export_id": bundle.id, "status": bundle.status.value, "clips": len(entries)}
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            failed = session.get(BundleExport, export_id)
            if failed is not None:
                failed.status = ExportStatus.FAILED
                failed.error_message = _truncate(str(exc))
                failed.finished_at = utcnow()
                session.commit()
            raise
