from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.drive_settings import DriveSettings
from app.drive_wizard import (
    WIZARD_AUTO_PLACE_MAX_IDS,
    auto_place_uploaded_file_ids,
    chunk_source_file_ids,
    merge_wizard_auto_place_payloads,
    _needs_manual_no_extension,
)


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


def test_needs_manual_no_extension() -> None:
    assert _needs_manual_no_extension("Makefile") is True
    assert _needs_manual_no_extension("a.pdf") is False


@patch("app.drive_wizard.library_folder_options")
@patch("app.drive_wizard.copy_drive_items_with_optional_rag")
@patch("app.drive_wizard.drive_google.ensure_folder_path_under_root")
def test_auto_place_pdf_ok(
    mock_ensure: MagicMock, mock_copy: MagicMock, mock_opts: MagicMock, drive_settings: DriveSettings
) -> None:
    mock_opts.return_value = [{"id": "libroot", "name": "(root)"}, {"id": "p1", "name": "PDF"}]
    mock_ensure.return_value = ("leaf1", [])
    mock_copy.return_value = {
        "ok": True,
        "results": [
            {
                "ok": True,
                "source_file_id": "f1",
                "copied_file_id": "c1",
                "copied_web_link": "https://example/c",
                "target_folder_name": "PDF",
                "name": "a.pdf",
            }
        ],
        "rag_chunks": 0,
    }
    svc = MagicMock()
    svc.files.return_value.get.return_value.execute.return_value = {
        "id": "f1",
        "name": "a.pdf",
        "mimeType": "application/pdf",
    }
    rag = MagicMock()
    rag.count.return_value = 42
    out = auto_place_uploaded_file_ids(
        svc,
        drive_settings,
        source_file_ids=["f1"],
        ingest_to_rag=False,
        rag=rag,
    )
    assert out["ok"] is True
    assert len(out["succeeded"]) == 1
    assert out["succeeded"][0]["file_id"] == "f1"
    assert not out["needs_manual"]
    assert out["rag_chunks"] == 42


@patch("app.drive_wizard.library_folder_options")
@patch("app.drive_wizard.copy_drive_items_with_optional_rag")
@patch("app.drive_wizard.drive_google.ensure_folder_path_under_root")
def test_auto_place_google_doc_manual(
    mock_ensure: MagicMock, mock_copy: MagicMock, mock_opts: MagicMock, drive_settings: DriveSettings
) -> None:
    mock_opts.return_value = [{"id": "libroot", "name": "(root)"}]
    svc = MagicMock()
    svc.files.return_value.get.return_value.execute.return_value = {
        "id": "g1",
        "name": "MyDoc",
        "mimeType": "application/vnd.google-apps.document",
    }
    rag = MagicMock()
    rag.count.return_value = 0
    out = auto_place_uploaded_file_ids(
        svc,
        drive_settings,
        source_file_ids=["g1"],
        ingest_to_rag=False,
        rag=rag,
    )
    assert len(out["needs_manual"]) == 1
    mock_ensure.assert_not_called()
    mock_copy.assert_not_called()


def test_chunk_source_file_ids_matches_wizard_limit() -> None:
    assert WIZARD_AUTO_PLACE_MAX_IDS == 120
    ids = [f"id{i}" for i in range(121)]
    chunks = chunk_source_file_ids(ids)
    assert len(chunks) == 2
    assert len(chunks[0]) == 120
    assert len(chunks[1]) == 1


def test_chunk_source_file_ids_strips_and_skips_empty() -> None:
    chunks = chunk_source_file_ids(["  a  ", "", "  b "])
    assert chunks == [["a", "b"]]


def test_merge_wizard_auto_place_payloads() -> None:
    a = {
        "ok": True,
        "succeeded": [{"file_id": "1"}],
        "needs_manual": [],
        "skipped": [{"file_id": "s"}],
        "folder_options": [{"id": "x"}],
        "rag_chunks": 5,
    }
    b = {
        "ok": True,
        "succeeded": [{"file_id": "2"}],
        "needs_manual": [{"file_id": "m"}],
        "skipped": [],
        "folder_options": [{"id": "y"}],
        "rag_chunks": 9,
    }
    m = merge_wizard_auto_place_payloads([a, b])
    assert len(m["succeeded"]) == 2
    assert len(m["needs_manual"]) == 1
    assert len(m["skipped"]) == 1
    assert m["folder_options"] == [{"id": "y"}]
    assert m["rag_chunks"] == 9


def test_wizard_auto_place_request_rejects_121_ids() -> None:
    from starlette.testclient import TestClient

    from app.main import app

    c = TestClient(app)
    ids = [f"x{i}" for i in range(121)]
    r = c.post("/drive/wizard/auto-place", json={"source_file_ids": ids, "ingest_to_rag": False})
    assert r.status_code == 422
