from __future__ import annotations

from pathlib import Path

import pytest

from app.path_security import assert_under_base, resolve_export_download, sanitize_subdir


def test_sanitize_subdir_rejects_traversal() -> None:
    assert sanitize_subdir("a/../../b") == "a/b"
    assert sanitize_subdir("/abs/path") == ""
    assert sanitize_subdir("ok/nested") == "ok/nested"


def test_resolve_export_download_ok(tmp_path: Path) -> None:
    base = tmp_path / "exports"
    base.mkdir()
    target = base / "Journal" / "x.md"
    target.parent.mkdir(parents=True)
    target.write_text("hi", encoding="utf-8")
    got = resolve_export_download(base, "Journal/x.md")
    assert got == target.resolve()


def test_resolve_export_download_rejects_escape(tmp_path: Path) -> None:
    base = tmp_path / "exports"
    base.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("no", encoding="utf-8")
    with pytest.raises(ValueError):
        resolve_export_download(base, "../secret.txt")


def test_resolve_rejects_nul(tmp_path: Path) -> None:
    base = tmp_path / "exports"
    base.mkdir()
    with pytest.raises(ValueError):
        resolve_export_download(base, "a\x00b")


def test_assert_under_base_allows_same_dir(tmp_path: Path) -> None:
    base = tmp_path / "v"
    base.mkdir()
    assert_under_base(base=base, target=base) == base.resolve()
