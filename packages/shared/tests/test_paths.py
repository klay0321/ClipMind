import os

import pytest

from clipmind_shared.security import (
    PathNotAllowed,
    PathTraversal,
    is_within,
    resolve_and_validate_root,
    safe_join_within_root,
)


def test_resolve_within_allowed_root(tmp_path):
    root = str(tmp_path)
    sub = tmp_path / "powergo"
    sub.mkdir()
    resolved = resolve_and_validate_root(str(sub), [root])
    assert resolved == os.path.realpath(str(sub))


def test_resolve_outside_allowed_root_raises(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(PathNotAllowed):
        resolve_and_validate_root(str(other), [str(allowed)])


def test_safe_join_ok(tmp_path):
    root = os.path.realpath(str(tmp_path))
    joined = safe_join_within_root(root, "a", "b.mp4")
    assert is_within(joined, root)


def test_safe_join_traversal_raises(tmp_path):
    root = os.path.realpath(str(tmp_path))
    with pytest.raises(PathTraversal):
        safe_join_within_root(root, "..", "escape.mp4")
