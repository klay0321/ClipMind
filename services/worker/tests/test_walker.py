import os

from clipmind_worker.scanning.walker import iter_video_files


def _rels(items):
    return sorted(rel.replace("\\", "/") for _abs, rel in items)


def test_filters_extensions_and_recurses(tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"x")
    (tmp_path / "b.txt").write_bytes(b"x")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "c.MOV").write_bytes(b"x")
    root = os.path.realpath(str(tmp_path))

    found = list(
        iter_video_files(
            root, recursive=True, include_extensions=["mp4", "mov"], exclude_patterns=[]
        )
    )
    assert _rels(found) == ["a.mp4", "sub/c.MOV"]


def test_non_recursive_only_top_level(tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"x")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "c.mp4").write_bytes(b"x")
    root = os.path.realpath(str(tmp_path))

    found = list(
        iter_video_files(root, recursive=False, include_extensions=["mp4"], exclude_patterns=[])
    )
    assert _rels(found) == ["a.mp4"]


def test_exclude_patterns(tmp_path):
    (tmp_path / "keep.mp4").write_bytes(b"x")
    (tmp_path / "skip.mp4").write_bytes(b"x")
    root = os.path.realpath(str(tmp_path))

    found = list(
        iter_video_files(
            root, recursive=True, include_extensions=["mp4"], exclude_patterns=["skip.*"]
        )
    )
    assert _rels(found) == ["keep.mp4"]
