from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class ArchiveResult:
    ok: bool
    destination: str
    path_or_url: str | None
    detail: str


class ArchiveSink(Protocol):
    """Unde „salvează” agentul sintezele (Notion, Obsidian, Drive…)."""

    def save_markdown_page(
        self,
        *,
        title: str,
        body_markdown: str,
        subdirectory: str | None = None,
    ) -> ArchiveResult: ...
