from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DriveSettings:
    stage_folder_id: str
    library_root_folder_id: str
    client_secret_path: Path
    token_path: Path
    memory_path: Path
    min_auto: int


def load_drive_settings(project_root: Path) -> DriveSettings | None:
    stage = (os.getenv("GOOGLE_DRIVE_STAGE_FOLDER_ID") or "").strip()
    root = (os.getenv("GOOGLE_DRIVE_LIBRARY_ROOT_FOLDER_ID") or "").strip()
    if not stage or not root:
        return None
    base = Path(
        os.getenv("GOOGLE_DRIVE_DATA_DIR", str(project_root / "data" / "drive"))
    ).resolve()
    client_secret = Path(
        os.getenv("GOOGLE_DRIVE_CLIENT_SECRET_PATH", str(base / "client_secret.json"))
    ).resolve()
    token = Path(os.getenv("GOOGLE_DRIVE_TOKEN_PATH", str(base / "token.json"))).resolve()
    memory = Path(
        os.getenv("GOOGLE_DRIVE_MEMORY_PATH", str(base / "placements.json"))
    ).resolve()
    try:
        min_auto = int((os.getenv("GOOGLE_DRIVE_MIN_AUTO") or "2").strip())
    except ValueError:
        min_auto = 2
    return DriveSettings(
        stage_folder_id=stage,
        library_root_folder_id=root,
        client_secret_path=client_secret,
        token_path=token,
        memory_path=memory,
        min_auto=max(0, min_auto),
    )
