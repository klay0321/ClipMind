"""audit_material_library 的单元测试（只读盘点脚本）。

测试均使用临时合成文件（绝不使用真实视频），覆盖：
  - 全程只读（源文件 size/mtime 不变、无新增/删除）
  - Windows 中文路径与中文文件名
  - 分级去重与移动识别
  - 分类证据（产品参考图 / 已使用 / 源视频）
  - “已使用”业务规则（不能据此判定次数/成片）
  - 路径安全（输出落在源目录内拒绝、源不存在安全退出）
"""

from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import audit_material_library as aml  # noqa: E402

# --------------------------------------------------------------------------- #
# 夹具
# --------------------------------------------------------------------------- #


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


@pytest.fixture
def material_root(tmp_path: Path) -> Path:
    """构造一个含中文路径、重复、已使用、产品参考图的合成素材根目录。"""
    root = tmp_path / "素材库测试"  # 中文根目录
    same = b"X" * 100_000          # 重复内容
    diff_a = b"A" * 100_000        # 同尺寸不同内容
    diff_b = b"B" * 100_000

    _write(root / "产品" / "恶魔之眼软屏" / "主图.png", b"\x89PNG\r\n" + b"0" * 2048)
    _write(root / "产品" / "mini键盘" / "宣传图.jpg", b"\xff\xd8\xff" + b"0" * 2048)
    _write(root / "20250919-键盘" / "kb_raw.mp4", diff_a)
    _write(root / "20251030-汽配" / "原片.mov", same)
    _write(root / "20251030-汽配" / "已使用" / "原片_已使用.mov", same)  # 重复 + 已使用
    _write(root / "20251030-汽配" / "另一条.mov", diff_b)               # 同尺寸不同内容
    _write(root / "产品" / "Thumbs.db", b"junk")                        # 系统垃圾
    return root


def _snapshot(root: Path) -> dict[str, tuple[int, int]]:
    snap = {}
    for p in root.rglob("*"):
        if p.is_file():
            st = p.stat()
            snap[str(p.relative_to(root)).replace("\\", "/")] = (st.st_size, st.st_mtime_ns)
    return snap


def _read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _norm(rel: str) -> str:
    return rel.replace("\\", "/")


# --------------------------------------------------------------------------- #
# 只读
# --------------------------------------------------------------------------- #


def test_run_audit_is_read_only(material_root: Path, tmp_path: Path) -> None:
    output = tmp_path / "out"
    before = _snapshot(material_root)

    rc = aml.run_audit(str(material_root), str(output))

    after = _snapshot(material_root)
    assert before == after, "源目录在审计后发生了变化（违反只读约束）"
    assert rc == 0
    summary_path = output / "audit_summary.json"
    assert summary_path.exists()
    import json

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["readonly_verification"]["read_only_ok"] is True
    assert summary["readonly_verification"]["added_count"] == 0
    assert summary["readonly_verification"]["removed_count"] == 0
    assert summary["readonly_verification"]["changed_count"] == 0


def test_all_expected_outputs_exist(material_root: Path, tmp_path: Path) -> None:
    output = tmp_path / "out"
    aml.run_audit(str(material_root), str(output))
    expected = [
        "audit_summary.md", "audit_summary.json", "inventory.csv",
        "product_catalog_draft.csv", "product_alias_draft.csv",
        "product_review_queue.csv", "source_video_candidates.csv",
        "final_video_candidates.csv", "used_evidence.csv",
        "duplicate_groups.csv", "possible_moves.csv", "unknown_media.csv",
        "errors.csv", "review_queue.csv", "benchmark_seed_candidates.csv",
        "query_labeling_template.csv", "usage_lineage_labeling_template.csv",
        "storyboard_labeling_template.csv",
    ]
    for name in expected:
        assert (output / name).exists(), f"缺少输出文件 {name}"


# --------------------------------------------------------------------------- #
# 中文路径
# --------------------------------------------------------------------------- #


def test_chinese_paths_inventoried(material_root: Path, tmp_path: Path) -> None:
    output = tmp_path / "out"
    aml.run_audit(str(material_root), str(output))
    rows = _read_csv(output / "inventory.csv")
    rels = {_norm(r["relpath"]) for r in rows}
    assert "产品/恶魔之眼软屏/主图.png" in rels
    assert "20251030-汽配/已使用/原片_已使用.mov" in rels


# --------------------------------------------------------------------------- #
# 去重 / 移动
# --------------------------------------------------------------------------- #


def test_duplicate_and_move_detection(material_root: Path, tmp_path: Path) -> None:
    output = tmp_path / "out"
    aml.run_audit(str(material_root), str(output))

    dups = _read_csv(output / "duplicate_groups.csv")
    # 恰好一组重复（两条相同内容的 .mov）
    assert len(dups) == 1
    grp = dups[0]
    assert int(grp["member_count"]) == 2
    members = {_norm(p.strip()) for p in grp["relpaths"].split(";")}
    assert "20251030-汽配/原片.mov" in members
    assert "20251030-汽配/已使用/原片_已使用.mov" in members

    moves = _read_csv(output / "possible_moves.csv")
    relations = {m["relation"] for m in moves}
    # 一条在已使用目录、一条不在 → 识别为 possible_move
    assert "possible_move" in relations


def test_same_size_different_content_not_merged(material_root: Path, tmp_path: Path) -> None:
    output = tmp_path / "out"
    aml.run_audit(str(material_root), str(output))
    dups = _read_csv(output / "duplicate_groups.csv")
    for grp in dups:
        members = {_norm(p.strip()) for p in grp["relpaths"].split(";")}
        # 同尺寸不同内容的两条不得被并入同一重复组
        assert not ({"20250919-键盘/kb_raw.mp4", "20251030-汽配/另一条.mov"} <= members)


# --------------------------------------------------------------------------- #
# 分类证据
# --------------------------------------------------------------------------- #


def test_classification_evidence(material_root: Path, tmp_path: Path) -> None:
    output = tmp_path / "out"
    aml.run_audit(str(material_root), str(output))
    rows = {_norm(r["relpath"]): r for r in _read_csv(output / "inventory.csv")}

    img = rows["产品/恶魔之眼软屏/主图.png"]
    assert img["classification"] == "product_reference_image"
    assert img["product_family"] == "恶魔之眼"
    assert img["product_variant"] == "软屏"

    used = rows["20251030-汽配/已使用/原片_已使用.mov"]
    assert used["classification"] == "used_source_candidate"

    kb = rows["20250919-键盘/kb_raw.mp4"]
    assert kb["classification"] == "source_video_candidate"
    assert kb["product_family"] == "小键盘"

    junk = rows["产品/Thumbs.db"]
    assert junk["classification"] == "system_junk"
    assert junk["needs_human"] == "no"


def test_used_evidence_business_rule(material_root: Path, tmp_path: Path) -> None:
    output = tmp_path / "out"
    aml.run_audit(str(material_root), str(output))
    used = _read_csv(output / "used_evidence.csv")
    assert used, "应至少有一条已使用证据"
    for row in used:
        # 业务规则：目录/后缀证据绝不能自动判定使用次数或对应成片
        assert row["can_determine_count"] == "no"
        assert row["can_determine_final"] == "no"
        assert row["needs_human"] == "yes"


# --------------------------------------------------------------------------- #
# 纯函数
# --------------------------------------------------------------------------- #


def test_match_products_pure() -> None:
    soft = aml.match_products("2026.04.28软屏")
    assert ("恶魔之眼", "软屏", "软屏") in soft

    kb = aml.match_products("20250919-键盘")
    families = {h[0] for h in kb}
    assert "小键盘" in families

    none = aml.match_products("无关目录abc")
    assert none == []


def test_detect_used_evidence_pure() -> None:
    ev = aml.detect_used_evidence("汽配/已使用/clip.mov")
    assert ev is not None
    assert ev["can_determine_count"] == "no"
    assert ev["can_determine_final"] == "no"
    assert aml.detect_used_evidence("汽配/原片/clip.mov") is None


def test_kind_of_pure() -> None:
    assert aml.kind_of(".png", "a.png") == "image"
    assert aml.kind_of(".MP4", "a.MP4") == "video"
    assert aml.kind_of(".db", "Thumbs.db") == "junk"
    assert aml.kind_of(".prproj", "proj.prproj") == "editor_project"


# --------------------------------------------------------------------------- #
# 路径安全
# --------------------------------------------------------------------------- #


def test_output_inside_root_rejected(material_root: Path) -> None:
    inside = material_root / "_audit_out"
    with pytest.raises(SystemExit):
        aml.assert_output_safe(str(material_root), str(inside))


def test_nonexistent_root_safe_exit(tmp_path: Path) -> None:
    missing = tmp_path / "不存在的目录"
    rc = aml.run_audit(str(missing), str(tmp_path / "out"))
    assert rc == 2
    # 不应创建任何输出（除非安全退出前未写入）
    assert not (tmp_path / "out" / "inventory.csv").exists()


def test_is_within_pure(tmp_path: Path) -> None:
    parent = tmp_path / "p"
    child = parent / "c" / "f.txt"
    parent.mkdir()
    (parent / "c").mkdir()
    child.write_text("x")
    assert aml.is_within(str(child), str(parent)) is True
    assert aml.is_within(str(tmp_path / "other"), str(parent)) is False


@pytest.mark.skipif(os.name != "nt", reason="目录软链测试针对 Windows 行为")
def test_dir_symlink_skipped(tmp_path: Path) -> None:
    root = tmp_path / "root"
    (root / "real").mkdir(parents=True)
    (root / "real" / "a.mp4").write_bytes(b"X" * 1000)
    link = root / "link"
    try:
        os.symlink(root / "real", link, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("无权限创建符号链接")
    errors: list = []
    files = list(aml.iter_files(str(root), errors))
    rels = {_norm(r) for _abs, r, _st in files}
    # 真实目录里的文件应出现，软链目录不应被递归
    assert "real/a.mp4" in rels
    assert any(e.error_reason == "dir_symlink_skipped" for e in errors)
