from datetime import UTC, datetime, timedelta

from clipmind_worker.scanning.diff import FileAction, decide_action, needs_probe

BASE = datetime(2026, 6, 23, 12, 0, 0, tzinfo=UTC)


def test_new():
    assert (
        decide_action(
            exists=False,
            is_source_missing=False,
            stored_size=None,
            stored_mtime=None,
            new_size=10,
            new_mtime=BASE,
        )
        == FileAction.NEW
    )


def test_unchanged():
    assert (
        decide_action(
            exists=True,
            is_source_missing=False,
            stored_size=10,
            stored_mtime=BASE,
            new_size=10,
            new_mtime=BASE,
        )
        == FileAction.UNCHANGED
    )


def test_modified_by_size():
    assert (
        decide_action(
            exists=True,
            is_source_missing=False,
            stored_size=10,
            stored_mtime=BASE,
            new_size=20,
            new_mtime=BASE,
        )
        == FileAction.MODIFIED
    )


def test_modified_by_mtime():
    assert (
        decide_action(
            exists=True,
            is_source_missing=False,
            stored_size=10,
            stored_mtime=BASE,
            new_size=10,
            new_mtime=BASE + timedelta(seconds=5),
        )
        == FileAction.MODIFIED
    )


def test_mtime_within_tolerance_is_unchanged():
    assert (
        decide_action(
            exists=True,
            is_source_missing=False,
            stored_size=10,
            stored_mtime=BASE,
            new_size=10,
            new_mtime=BASE + timedelta(milliseconds=500),
        )
        == FileAction.UNCHANGED
    )


def test_reappeared():
    assert (
        decide_action(
            exists=True,
            is_source_missing=True,
            stored_size=10,
            stored_mtime=BASE,
            new_size=10,
            new_mtime=BASE,
        )
        == FileAction.REAPPEARED
    )


def test_needs_probe():
    assert needs_probe(FileAction.NEW) is True
    assert needs_probe(FileAction.MODIFIED) is True
    assert needs_probe(FileAction.REAPPEARED) is True
    assert needs_probe(FileAction.UNCHANGED) is False
