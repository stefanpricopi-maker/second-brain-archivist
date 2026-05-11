#!/usr/bin/env python3
"""
Autentificare OAuth Google Drive (Desktop app) — generează token.json.

1. În Google Cloud Console: creează OAuth client „Desktop app”, descarcă JSON-ul.
2. Salvează fișierul ca `data/drive/client_secret.json` (sau GOOGLE_DRIVE_CLIENT_SECRET_PATH).
3. Rulează din rădăcina proiectului:

    python scripts/drive_auth.py

4. Deschide browserul, acceptă permisiunile.

Fișierul token se scrie la `data/drive/token.json` (sau GOOGLE_DRIVE_TOKEN_PATH).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from google_auth_oauthlib.flow import InstalledAppFlow

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")

from app.drive_google import SCOPES  # noqa: E402


def main() -> None:
    project_root = PROJECT_ROOT
    base = Path(os.getenv("GOOGLE_DRIVE_DATA_DIR", str(project_root / "data" / "drive"))).resolve()
    client_secret = Path(
        os.getenv("GOOGLE_DRIVE_CLIENT_SECRET_PATH", str(base / "client_secret.json"))
    ).resolve()
    token_path = Path(os.getenv("GOOGLE_DRIVE_TOKEN_PATH", str(base / "token.json"))).resolve()

    if not client_secret.is_file():
        raise SystemExit(f"Lipsește {client_secret} — pune client_secret din Google Cloud acolo.")

    token_path.parent.mkdir(parents=True, exist_ok=True)
    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent")
    token_path.write_text(creds.to_json(), encoding="utf-8")
    print(f"OK: token salvat la {token_path}")


if __name__ == "__main__":
    main()
