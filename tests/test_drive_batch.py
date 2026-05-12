from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.drive_batch import batch_auto_organize_from_folder, gather_source_files
from app.drive_settings import DriveSettings


@pytest.fixture
def drive_settings(tmp_path: Path) -> DriveSettings:
    mem = tmp_path / "placements.json"
    mem.write_text(json.dumps({"copied_source_ids": [], "placements": []}), encoding="utf-8")
    return DriveSettings(
        stage_folder_id="stage1",
        library_root_folder_id="libroot",
        client_secret_path=tmp_path / "cs.json",
        token_path=tmp_path / "tk.json",
        memory_path=mem,
        min_auto=2,
        theme_paths_enabled=True,
    )


def test_recursive_rejects_library_root(drive_settings: DriveSettings) -> None:
    svc = MagicMock()
    out = batch_auto_organize_from_folder(
        svc,
        drive_settings,
        source_folder_id=drive_settings.library_root_folder_id,
        recursive=True,
        max_files=10,
        ingest_to_rag=False,
        rag=MagicMock(),
        pause_sec=0.0,
    )
    assert out.get("ok") is False


@patch("app.drive_batch.gather_source_files")
@patch("app.drive_batch.drive_google.ensure_folder_path_under_root")
@patch("app.drive_batch.copy_drive_items_with_optional_rag")
def test_batch_copies_one_pdf(
    mock_copy: MagicMock,
    mock_ensure: MagicMock,
    mock_gather: MagicMock,
    drive_settings: DriveSettings,
) -> None:
    mock_gather.return_value = [
        {"id": "fileA", "name": "a.pdf", "mimeType": "application/pdf"},
    ]
    mock_ensure.return_value = ("leaf1", ["PDF"])
    mock_copy.return_value = {
        "ok": True,
        "results": [{"ok": True, "copied_file_id": "c1", "copied_web_link": "https://x"}],
        "rag_chunks": 0,
    }
    rag = MagicMock()
    rag.count.return_value = 0
    svc = MagicMock()
    out = batch_auto_organize_from_folder(
        svc,
        drive_settings,
        source_folder_id="inbox",
        recursive=False,
        max_files=10,
        ingest_to_rag=False,
        rag=rag,
        pause_sec=0.0,
    )
    assert out["ok"] is True
    assert out["scanned_count"] == 1
    assert out["copied_ok"] == 1
    assert out["skipped_count"] == 0
    mock_copy.assert_called_once()


@patch("app.drive_batch.gather_source_files")
@patch("app.drive_batch.copy_drive_items_with_optional_rag")
def test_batch_skips_already_copied(mock_copy: MagicMock, mock_gather: MagicMock, drive_settings: DriveSettings) -> None:
    st = json.loads(drive_settings.memory_path.read_text(encoding="utf-8"))
    st["copied_source_ids"] = ["fileA"]
    drive_settings.memory_path.write_text(json.dumps(st), encoding="utf-8")

    mock_gather.return_value = [{"id": "fileA", "name": "a.pdf", "mimeType": "application/pdf"}]
    svc = MagicMock()
    out = batch_auto_organize_from_folder(
        svc,
        drive_settings,
        source_folder_id="inbox",
        recursive=False,
        max_files=10,
        ingest_to_rag=False,
        rag=MagicMock(),
        pause_sec=0.0,
    )
    assert out["copied_ok"] == 0
    assert out["skipped_count"] == 1
    mock_copy.assert_not_called()


def test_gather_non_recursive_calls_list(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[str] = []

    def fake_list(service: object, folder_id: str) -> list[dict]:
        called.append(folder_id)
        return [{"id": "1", "name": "a.pdf", "mimeType": "application/pdf"}]

    monkeypatch.setattr("app.drive_google.list_nonfolder_children", fake_list)
    svc = MagicMock()
    out = gather_source_files(svc, "F1", recursive=False, max_files=5)
    assert len(out) == 1
    assert called == ["F1"]
