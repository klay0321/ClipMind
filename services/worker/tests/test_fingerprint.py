import os

from clipmind_worker.scanning.fingerprint import compute_quick_hash


def _hash(path):
    return compute_quick_hash(str(path), os.stat(path).st_size)


def test_stable_for_same_content(tmp_path):
    p = tmp_path / "f.bin"
    p.write_bytes(b"a" * 1000)
    assert _hash(p) == _hash(p)


def test_changes_with_content(tmp_path):
    p = tmp_path / "f.bin"
    p.write_bytes(b"a" * 1000)
    h1 = _hash(p)
    p.write_bytes(b"b" * 1000)
    h2 = _hash(p)
    assert h1 != h2


def test_changes_with_size(tmp_path):
    p = tmp_path / "f.bin"
    p.write_bytes(b"a" * 1000)
    h1 = _hash(p)
    p.write_bytes(b"a" * 2000)
    h2 = _hash(p)
    assert h1 != h2


def test_large_file_head_change_detected(tmp_path):
    p = tmp_path / "big.bin"
    size = 200 * 1024
    p.write_bytes(b"\x00" * size)
    h1 = _hash(p)
    data = bytearray(b"\x00" * size)
    data[0:10] = b"\x01" * 10  # 修改头部
    p.write_bytes(bytes(data))
    h2 = _hash(p)
    assert h1 != h2
