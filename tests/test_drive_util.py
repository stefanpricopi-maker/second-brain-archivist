from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from app.drive_util import folder_id_from_drive_url


def test_folder_id_from_drive_url() -> None:
    u = "https://drive.google.com/drive/u/0/folders/1PNa95NefhlPYWl26TX5rtyqn1yk0m359"
    assert folder_id_from_drive_url(u) == "1PNa95NefhlPYWl26TX5rtyqn1yk0m359"
    assert folder_id_from_drive_url("13MMK7oKRfgUIvGTEy_v0d_3uTB_lnW0G") == "13MMK7oKRfgUIvGTEy_v0d_3uTB_lnW0G"
    assert folder_id_from_drive_url("") is None


@pytest.fixture
def client() -> TestClient:
    from app.main import app

    return TestClient(app)


def test_drive_folder_id_endpoint(client: TestClient) -> None:
    r = client.get(
        "/drive/folder-id",
        params={"url": "https://drive.google.com/drive/u/0/folders/abcXYZ09-_"},
    )
    assert r.status_code == 200
    assert r.json().get("folder_id") == "abcXYZ09-_"


def test_drive_status(client: TestClient) -> None:
    r = client.get("/drive/status")
    assert r.status_code == 200
    body = r.json()
    assert "enabled" in body
