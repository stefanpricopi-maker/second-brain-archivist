# Plan de teste — v0.1

## Automat (pytest)

- `GET /health`, `GET /status` — `tests/test_smoke.py`
- `GET /search` — lipsă `q` → eroare validată; index gol → `results == []`
- `POST /chat` — cu `LLM_MODE=disabled` → răspuns non-gol
- `POST /archive/page` — `ok: true` cu sink de download (stub) sau Obsidian dacă vault e setat în mediu
- **Ingest / RAG:** `tests/test_ingest_bytes_rag.py` (fluxuri chunk + index)
- **EPUB:** `tests/test_epub_ingest.py` (cu `ebooklib`)
- **Notion:** `tests/test_notion_sink.py` (mock HTTP spre API Notion)
- **Drive (fără rețea reală):** `tests/test_drive_util.py`, `test_drive_extension_paths.py`, `test_drive_batch.py`, `test_drive_wizard.py` (chunking wizard, merge payload, validare 121 ID-uri → 422), smoke UI statică conține rute wizard

## Manual

1. Ingest PDF scurt + EPUB + `GET /search?q=...` cu hit-uri.
2. `OBSIDIAN_VAULT_PATH` la un folder de test → `POST /archive/page` → fișier creat.
3. MCP: `library_search` din Cursor pe același index.
4. Drive: OAuth + upload în Stage din UI → plasare automată; sau MCP `drive_status` / `drive_wizard_auto_place` cu token valid (acceptă costuri API / cote).

## Viitor (teste)

- **OCR** — suite dedicată când există pipeline de extragere.
- **Contract / integrare Drive** împotriva API real (opțional, în CI cu secret sau doar local): smoke scurt cu folder de test.
