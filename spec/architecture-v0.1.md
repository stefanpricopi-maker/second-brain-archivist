# Arhitectură — v0.1

## Componente

```
[data/library + knowledge/public]  →  ingest (script + POST /ingest/files)  →  Chroma (vectorstore)
                                                                                    ↓
User / UI statică  →  FastAPI (health, search, chat, archive, ingest, Drive)  ←  OpenAI (opțional)
Cursor MCP  ────────→  FastAPI (aceleași servicii) + unelte MCP (search, arhivă, Drive)
                              ↓
        ArchiveSink: ObsidianVaultSink | NotionSink | BrowserDownloadSink
                              ↓
        Drive: OAuth → Google API (Stage, bibliotecă, copiere, wizard auto-place, batch)
```

## Decizii

- **Chroma persistent** sub `VECTORSTORE_DIR` — același model ca în kit-ul Audi (embedding implicit Chroma).
- **Separare RAG vs arhivă:** căutarea nu scrie niciodată în vault; scrieri doar prin `archive/*`, ingest și fluxurile Drive/MCP asociate.
- **Obsidian:** scriere fișier `.md` pe disc — fără API cloud; utilizatorul sincronizează (iCloud/Git) dacă dorește.
- **Notion:** `NotionSink` + variabile `.env` (token, parent unic); MCP `notion_create_page` și `POST /archive/page` când Notion e prioritar față de Obsidian.
- **Google Drive:** OAuth utilizator, folder Stage + rădăcină bibliotecă; copiere (originalul poate rămâne în Stage); subfoldere după extensie configurabile (`GOOGLE_DRIVE_THEME_PATHS`); memorie copieri în JSON local; opțional ingest RAG după copiere.
- **EPUB:** `ebooklib` + extragere pe capitole + același pipeline de chunking ca PDF/text.

## Roadmap (în afara v0.1 „închis”)

- **OCR** pentru PDF-uri scanate (fără strat text selectabil).
- **RAG din Notion** automat — în continuare neobiectiv: export manual sau copiere în bibliotecă + ingest.

## Securitate

- Token-uri Notion/Drive doar în `.env` sau secret manager; niciodată în repo.
- Path traversal: `subdirectory` sanitizat în `ObsidianVaultSink` (`..` eliminat); `GET /archive/files/…` și exporturi validate (`app/path_security.py`).
- **Request ID** și rate limiting: vezi `README.md` (hardening).
