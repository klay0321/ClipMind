from clipmind_shared.pathutil import normalize_relative_path


def test_backslash_to_slash():
    assert normalize_relative_path("a\\b\\c.mp4") == "a/b/c.mp4"


def test_strip_and_collapse():
    assert normalize_relative_path("/a//b/./c.mp4") == "a/b/c.mp4"


def test_empty():
    assert normalize_relative_path("") == ""
    assert normalize_relative_path("/") == ""
