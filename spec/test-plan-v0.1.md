# Plan de teste — v0.1

## Automat (pytest)

- `GET /health`, `GET /status`
- `GET /search` — lipsă `q` → 400/422; index gol → `results == []`
- `POST /chat` — `LLM_MODE=disabled` → răspuns non-gol
- `POST /archive/page` — `ok: true` (stub sau obsidian dacă vault setat în CI — de obicei stub)

## Manual

1. Ingest un PDF scurt + `GET /search?q=...` cu hit-uri.
2. Setează `OBSIDIAN_VAULT_PATH` la un folder de test; `archive` → fișier creat.
3. MCP: `library_search` din Cursor cu același index.

## Viitor

- Contract test pentru Notion API (mock HTTP).
- Test ingest EPUB când `ebooklib` e adăugat.
