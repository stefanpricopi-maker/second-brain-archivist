from __future__ import annotations

import re
from typing import Any, Callable

import httpx

from app.connectors.base import ArchiveResult

NOTION_VERSION = "2022-06-28"
NOTION_BASE = "https://api.notion.com/v1"

# Semnătură: (method, path_relative_to_v1, json_body) -> răspuns JSON
NotionRequestFn = Callable[[str, str, dict[str, Any]], dict[str, Any]]


def _split_rich_segments(text: str, limit: int = 1900) -> list[dict[str, Any]]:
    """Notion limitează ~2000 caractere per obiect text; păstrăm marjă."""
    text = text or ""
    parts: list[dict[str, Any]] = []
    i = 0
    while i < len(text):
        parts.append({"type": "text", "text": {"content": text[i : i + limit]}})
        i += limit
    return parts if parts else [{"type": "text", "text": {"content": ""}}]


def markdown_to_notion_blocks(markdown: str) -> list[dict[str, Any]]:
    """Parser minimal: paragrafe + titluri # .. ######."""
    blocks: list[dict[str, Any]] = []
    chunks = re.split(r"\n{2,}", (markdown or "").strip())
    for raw in chunks:
        line = raw.strip()
        if not line:
            continue
        m = re.match(r"^(#{1,6})\s+(.+)$", line, flags=re.DOTALL)
        if m and "\n" not in m.group(2):
            level = len(m.group(1))
            title = m.group(2).strip()
            if level == 1:
                btype = "heading_1"
            elif level == 2:
                btype = "heading_2"
            else:
                btype = "heading_3"
            blocks.append({btype: {"rich_text": _split_rich_segments(title)}, "type": btype})
            continue
        blocks.append({"type": "paragraph", "paragraph": {"rich_text": _split_rich_segments(line)}})
    if not blocks:
        blocks.append({"type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": ""}}]}})
    for b in blocks:
        b.setdefault("object", "block")
    return blocks


def _notion_page_url(page_id: str) -> str:
    pid = page_id.replace("-", "")
    return f"https://www.notion.so/{pid}"


class NotionArchiveSink:
    """
    Creează o pagină Notion (copil al unei pagini sau rând într-o bază de date).
    Necesită integration cu acces la parent.
    """

    def __init__(
        self,
        token: str,
        *,
        parent_page_id: str | None = None,
        database_id: str | None = None,
        title_property: str = "Name",
        request: NotionRequestFn | None = None,
    ):
        if not token.strip():
            raise ValueError("NOTION_TOKEN lipsă.")
        if bool(parent_page_id) == bool(database_id):
            raise ValueError("Setează exact unul dintre: parent_page_id sau database_id.")
        self._token = token.strip()
        self._parent_page = (parent_page_id or "").strip() or None
        self._database = (database_id or "").strip() or None
        self._title_property = (title_property or "Name").strip() or "Name"
        self._request_fn: NotionRequestFn = request or self._httpx_request

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }

    def _httpx_request(self, method: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
        url = f"{NOTION_BASE}/{path.lstrip('/')}"
        with httpx.Client(timeout=60.0) as client:
            r = client.request(method.upper(), url, json=body, headers=self._headers())
            try:
                r.raise_for_status()
            except httpx.HTTPStatusError as e:
                detail = ""
                try:
                    detail = str(r.json().get("message", r.text))[:2000]
                except Exception:
                    detail = r.text[:2000]
                raise RuntimeError(f"Notion API {r.status_code}: {detail}") from e
            if not r.content:
                return {}
            return r.json()

    def _append_children(self, block_id: str, children: list[dict[str, Any]]) -> None:
        batch = 100
        for i in range(0, len(children), batch):
            chunk = children[i : i + batch]
            self._request_fn("PATCH", f"blocks/{block_id}/children", {"children": chunk})

    def save_markdown_page(
        self,
        *,
        title: str,
        body_markdown: str,
        subdirectory: str | None = None,
    ) -> ArchiveResult:
        title = (title or "").strip() or "Untitled"
        body = body_markdown or ""
        if subdirectory and str(subdirectory).strip():
            body = f"### {str(subdirectory).strip()}\n\n" + body

        all_blocks = markdown_to_notion_blocks(body)
        first_batch = all_blocks[:100]
        rest = all_blocks[100:]

        if self._database:
            props = {
                self._title_property: {
                    "title": [{"type": "text", "text": {"content": title[:2000]}}],
                }
            }
            payload: dict[str, Any] = {
                "parent": {"database_id": self._database},
                "properties": props,
            }
            if first_batch:
                payload["children"] = first_batch
        else:
            assert self._parent_page is not None
            payload = {
                "parent": {"page_id": self._parent_page},
                "properties": {
                    self._title_property: {
                        "title": [{"type": "text", "text": {"content": title[:2000]}}],
                    }
                },
            }
            if first_batch:
                payload["children"] = first_batch

        try:
            created = self._request_fn("POST", "pages", payload)
        except Exception as e:
            return ArchiveResult(
                ok=False,
                destination="notion",
                path_or_url=None,
                detail=str(e),
            )

        page_id = str(created.get("id") or "")
        if not page_id:
            return ArchiveResult(
                ok=False,
                destination="notion",
                path_or_url=None,
                detail="Răspuns Notion fără id pagină.",
            )

        if rest:
            try:
                self._append_children(page_id, rest)
            except Exception as e:
                return ArchiveResult(
                    ok=False,
                    destination="notion",
                    path_or_url=_notion_page_url(page_id),
                    detail=f"Pagină creată, dar blocuri incomplete: {e}",
                )

        url = str(created.get("url") or "").strip()
        if not url:
            url = _notion_page_url(page_id)
        return ArchiveResult(
            ok=True,
            destination="notion",
            path_or_url=url,
            detail="Pagină creată în Notion.",
        )


def load_notion_sink_from_env(*, request: NotionRequestFn | None = None) -> NotionArchiveSink | None:
    import os

    token = (os.getenv("NOTION_TOKEN") or "").strip()
    page = (os.getenv("NOTION_PARENT_PAGE_ID") or "").strip()
    db = (os.getenv("NOTION_DATABASE_ID") or "").strip()
    title_prop = (os.getenv("NOTION_TITLE_PROPERTY") or "").strip()
    if not token:
        return None
    if bool(page) == bool(db):
        return None
    default_title = "Name" if db else "title"
    tp = title_prop or default_title
    return NotionArchiveSink(
        token,
        parent_page_id=page or None,
        database_id=db or None,
        title_property=tp,
        request=request,
    )
