from __future__ import annotations

from app.connectors.base import ArchiveResult, ArchiveSink


class StubArchiveSink:
    """Fără integrare externă: returnează doar confirmare simulată (teste, demo)."""

    def save_markdown_page(
        self,
        *,
        title: str,
        body_markdown: str,
        subdirectory: str | None = None,
    ) -> ArchiveResult:
        sub = (subdirectory or "inbox").strip("/").replace("..", "")
        return ArchiveResult(
            ok=True,
            destination="stub",
            path_or_url=f"{sub}/{title[:40]}.md",
            detail="Stub: nu s-a scris pe disc. Configurează OBSIDIAN_VAULT_PATH sau integrare Notion.",
        )
