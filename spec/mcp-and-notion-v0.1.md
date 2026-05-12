# MCP & integrări cloud — v0.1

## Ce există acum (MCP)

| Tool MCP | Descriere |
|----------|-----------|
| `library_search` | JSON cu fragmente din Chroma (`query`, `k`). |
| `library_chunk_count` | Număr de fragmente în colecția Chroma. |
| `archive_save_markdown_page` | Obsidian dacă `OBSIDIAN_VAULT_PATH`, altfel Notion dacă token+parent, altfel download în `EXPORTS_DIR`. |
| `notion_create_page` | Creează pagină Notion (ignoră Obsidian); necesită `NOTION_TOKEN` + exact un parent (pagină sau bază de date). |
| `drive_status` | JSON: config Drive (.env), prezență client secret / token, `stage_folder_id`, `library_root_folder_id`. |
| `drive_library_folders` | Listează folderele țintă sub rădăcina bibliotecii (Drive API). |
| `drive_propose_stage` | Scanează Stage, propune plasări (bootstrap sau LLM dacă e activ). |
| `drive_copy_items` | Copiază din Stage în bibliotecă după mapare explicită; `items_json` = listă sau obiect cu `ingest_to_rag`. |
| `drive_wizard_auto_place` | Plasare automată după extensie (ca `POST /drive/wizard/auto-place`): primește JSON array de `file_id`; liste >120 ID-uri sunt împărțite server-side și rezultatele unite. |

Server: `python -m mcp_server.server`, **cwd** = rădăcina proiectului. Detalii `.env` în `README.md`.

## Notion (implementat v0.1)

1. **Notion API** `POST /v1/pages` + `PATCH /v1/blocks/{id}/children` (max 100 blocuri per cerere).
2. Variabile: `NOTION_TOKEN`, exact unul dintre `NOTION_PARENT_PAGE_ID` sau `NOTION_DATABASE_ID`, opțional `NOTION_TITLE_PROPERTY` (implicit `Name` pentru DB, `title` pentru pagină copil).
3. MCP: `notion_create_page(title, body_markdown, subdirectory?)` — același flux ca arhiva Notion din API.
4. RAG **nu** citește automat Notion — export / copiere în `data/library/` + ingest separat.

## Google Drive (implementat)

1. **OAuth 2.0 utilizator** (client **Desktop**): `data/drive/client_secret.json`, `python scripts/drive_auth.py` → `data/drive/token.json`. Variabile: `GOOGLE_DRIVE_STAGE_FOLDER_ID`, `GOOGLE_DRIVE_LIBRARY_ROOT_FOLDER_ID`, opțional `GOOGLE_DRIVE_STAGE_FOLDER_URL`, `GOOGLE_DRIVE_THEME_PATHS`, `GOOGLE_DRIVE_MIN_AUTO`.
2. **API FastAPI** (rezumat): `GET /drive/status`, `GET /drive/folders`, `POST /drive/stage/upload`, `POST /drive/propose`, `POST /drive/copy`, `POST /drive/wizard/auto-place` (max 120 `source_file_ids` per cerere; UI și MCP împart listele mai lungi), `POST /drive/batch/auto-organize`, utilitare (`/drive/folder-id`, etc.). Vezi `/docs`.
3. **UI** (`/static/index.html`): tab Drive — wizard (conexiune → upload Stage în paralel limitat → plasare automată / manual); secțiune avansată pentru bulk.
4. **MCP:** uneltele din tabelul de mai sus; același cod de business ca în `app/` (fără duplicare de reguli pe extensii).

### Opțional / viitor (nu e în v0.1)

- **Cont de serviciu (service account)** pentru Workspace — alt model de permisiuni față de OAuth desktop; neplanificat explicit în acest document.
- **OCR pentru PDF scanate** — ingest text din scanări; vezi roadmap în `README.md`.

## Obsidian „cloud”

Obsidian nu expune API cloud unificat: de obicei **folder local** (Sync, Git, iCloud mirror). V0.1 scrie direct în acel folder.

## Cursor

În setări MCP, adaugă server cu:

- **Command:** `python` (sau cale absolută la venv)
- **Args:** `-m`, `mcp_server.server`
- **Cwd:** rădăcina acestui proiect
