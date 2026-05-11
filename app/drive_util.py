from __future__ import annotations

import re


def folder_id_from_drive_url(url: str) -> str | None:
    """Extrage folder ID din URL-uri de tipul https://drive.google.com/drive/.../folders/<id>."""
    s = (url or "").strip()
    m = re.search(r"/folders/([a-zA-Z0-9_-]+)", s)
    if m:
        return m.group(1)
    m2 = re.search(r"id=([a-zA-Z0-9_-]+)", s)
    if m2:
        return m2.group(1)
    if re.fullmatch(r"[a-zA-Z0-9_-]+", s):
        return s
    return None
