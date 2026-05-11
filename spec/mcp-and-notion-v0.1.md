# MCP & integrări cloud — v0.1

## Ce există acum

| Tool MCP | Descriere |
|----------|-----------|
| `library_search` | JSON cu fragmente din Chroma |
| `library_chunk_count` | dimensiune index |
| `archive_save_markdown_page` | Obsidian dacă `OBSIDIAN_VAULT_PATH`, altfel stub |

## Notion (roadmap)

1. Integrare **Notion API** (REST): creare pagină în workspace, blocuri `paragraph` / `heading` din Markdown simplu.
2. Variabile: `NOTION_TOKEN` (integration secret), `NOTION_PARENT_ID` (pagină sau database).
3. MCP tool: `notion_create_page(title, blocks_json)` sau adaptare din `body_markdown` cu parser minimal.
4. RAG **nu** citește automat paginile Notion — export manual sau job separat de export → `data/library/`.

## Google Drive (roadmap)

- OAuth2 user flow sau service account (workspace).
- Tool: `drive_upload_markdown` sau sync fișiere exportate.

## Obsidian „cloud”

Obsidian nu expune API cloud unificat: de obicei **folder local** (Sync, Git, iCloud mirror). V0.1 scrie direct în acel folder.

## Cursor

În setări MCP, adaugă server cu:

- **Command:** `python` (sau cale absolută la venv)
- **Args:** `-m`, `mcp_server.server`
- **Cwd:** rădăcina acestui proiect
