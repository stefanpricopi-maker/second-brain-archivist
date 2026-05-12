from __future__ import annotations

from typing import Any

from app.connectors.notion_api import NotionArchiveSink, markdown_to_notion_blocks


def test_markdown_to_blocks_heading_and_paragraph() -> None:
    blocks = markdown_to_notion_blocks("## Titlu\n\nParagraf unu.\n\nAl doilea.")
    assert len(blocks) >= 2
    assert all(b.get("object") == "block" for b in blocks)
    types = [b.get("type") for b in blocks]
    assert "heading_2" in types
    assert "paragraph" in types


def test_notion_database_create_ok() -> None:
    calls: list[tuple[str, str, dict[str, Any]]] = []

    def fake_request(method: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
        calls.append((method, path, body))
        if method == "POST" and path == "pages":
            return {
                "id": "aaaaaaaa-bbbb-cccc-dddd-111111111111",
                "url": "https://www.notion.so/Test-aaaaaaaabbbbccccdddd111111111111",
            }
        if method == "PATCH" and path.startswith("blocks/") and path.endswith("/children"):
            return {"results": []}
        raise AssertionError((method, path))

    sink = NotionArchiveSink(
        "secret_token",
        database_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        title_property="Name",
        request=fake_request,
    )
    res = sink.save_markdown_page(title="Hello", body_markdown="Body text\n\nSecond.")
    assert res.ok is True
    assert res.destination == "notion"
    assert res.path_or_url and "notion.so" in res.path_or_url
    assert calls and calls[0][0] == "POST"
    assert calls[0][2]["parent"]["database_id"]


def test_notion_append_when_over_100_blocks() -> None:
    calls: list[tuple[str, str]] = []

    def fake_request(method: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
        calls.append((method, path))
        if method == "POST" and path == "pages":
            return {"id": "page-uuid-1111-2222-3333-444444444444"}
        if method == "PATCH":
            return {}
        raise AssertionError((method, path))

    # 120 paragrafe scurte => primul POST cu 100 copii, apoi PATCH
    md = "\n\n".join(f"p{i}" for i in range(120))
    sink = NotionArchiveSink(
        "secret_token",
        parent_page_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        title_property="title",
        request=fake_request,
    )
    res = sink.save_markdown_page(title="Big", body_markdown=md)
    assert res.ok is True
    post_pages = [c for c in calls if c == ("POST", "pages")]
    patch_children = [c for c in calls if c[0] == "PATCH" and "/children" in c[1]]
    assert len(post_pages) == 1
    assert len(patch_children) >= 1


def test_notion_api_error_surfaces() -> None:
    def boom(_m: str, _p: str, _b: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("Notion API 401: Unauthorized")

    sink = NotionArchiveSink(
        "bad",
        database_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        request=boom,
    )
    res = sink.save_markdown_page(title="X", body_markdown="y")
    assert res.ok is False
    assert "401" in res.detail or "Unauthorized" in res.detail
