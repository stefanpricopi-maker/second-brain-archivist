from __future__ import annotations

import re
from pathlib import Path

from app.connectors.base import ArchiveResult, ArchiveSink
from app.path_security import assert_under_base, sanitize_subdir


def _safe_segment(name: str) -> str:
    name = re.sub(r"[^\w\s\-ăâîșțĂÂÎȘȚ]", "", name, flags=re.UNICODE).strip()
    return name[:120] or "untitled"


class ObsidianVaultSink:
    """Scrie fișier .md în vaultul Obsidian (folder local)."""

    def __init__(self, vault_root: Path, default_subdir: str = "SecondBrain/Inbox"):
        self.vault_root = vault_root.expanduser().resolve()
        self.default_subdir = sanitize_subdir(default_subdir) or "SecondBrain/Inbox"

    def save_markdown_page(
        self,
        *,
        title: str,
        body_markdown: str,
        subdirectory: str | None = None,
    ) -> ArchiveResult:
        if not self.vault_root.is_dir():
            return ArchiveResult(
                ok=False,
                destination="obsidian",
                path_or_url=None,
                detail=f"Vault nu există sau nu e director: {self.vault_root}",
            )
        sub = sanitize_subdir(subdirectory or self.default_subdir) or self.default_subdir
        folder = (self.vault_root / sub).resolve()
        try:
            assert_under_base(base=self.vault_root, target=folder)
        except ValueError:
            return ArchiveResult(
                ok=False,
                destination="obsidian",
                path_or_url=None,
                detail="Subdirector invalid (traversal respins).",
            )
        folder.mkdir(parents=True, exist_ok=True)
        fname = _safe_segment(title) + ".md"
        path = folder / fname
        header = f"---\ntitle: {title}\n---\n\n"
        path.write_text(header + body_markdown, encoding="utf-8")
        return ArchiveResult(
            ok=True,
            destination="obsidian",
            path_or_url=str(path),
            detail="Pagină Markdown creată în vault.",
        )
