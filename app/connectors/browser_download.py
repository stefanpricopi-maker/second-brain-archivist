from __future__ import annotations

import re
import time
import uuid
from pathlib import Path

from app.connectors.base import ArchiveResult
from app.path_security import assert_under_base, sanitize_subdir


def _safe_segment(name: str) -> str:
    name = re.sub(r"[^\w\s\-ăâîșțĂÂÎȘȚ]", "", name, flags=re.UNICODE).strip()
    name = re.sub(r"\s+", " ", name)
    return name[:120] or "untitled"


class BrowserDownloadSink:
    """Salvează un .md într-un folder servit de API (download din Chrome)."""

    def __init__(self, exports_dir: Path):
        self.exports_dir = exports_dir.expanduser().resolve()
        self.exports_dir.mkdir(parents=True, exist_ok=True)

    def save_markdown_page(
        self,
        *,
        title: str,
        body_markdown: str,
        subdirectory: str | None = None,
    ) -> ArchiveResult:
        sub = sanitize_subdir(subdirectory or "")
        folder = (self.exports_dir / sub).resolve() if sub else self.exports_dir.resolve()
        try:
            assert_under_base(base=self.exports_dir, target=folder)
        except ValueError:
            return ArchiveResult(
                ok=False,
                destination="download",
                path_or_url=None,
                detail="Subdirector invalid (traversal respins).",
            )
        folder.mkdir(parents=True, exist_ok=True)

        stamp = time.strftime("%Y%m%d-%H%M%S")
        fname = f"{stamp}__{uuid.uuid4().hex[:10]}__{_safe_segment(title)}.md"
        path = folder / fname
        header = f"---\ntitle: {title}\n---\n\n"
        path.write_text(header + body_markdown, encoding="utf-8")

        rel = path.relative_to(self.exports_dir)
        url_path = "/archive/files/" + str(rel).replace("\\", "/")
        return ArchiveResult(
            ok=True,
            destination="download",
            path_or_url=url_path,
            detail="Fișier creat în exports; deschide link-ul în Chrome pentru download.",
        )

