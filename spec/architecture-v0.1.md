# Arhitectură — v0.1

## Componente

```
[data/library + knowledge/public]  →  ingest_library.py  →  Chroma (vectorstore)
                                                              ↓
User / Cursor MCP  →  FastAPI (search, chat, archive)  ←  OpenAI (opțional)
                         ↓
                   ArchiveSink: ObsidianVaultSink | StubArchiveSink
```

## Decizii

- **Chroma persistent** sub `VECTORSTORE_DIR` — același model ca în kit-ul Audi (embedding implicit Chroma).
- **Separare RAG vs arhivă:** căutarea nu scrie niciodată în vault; doar `archive/*` și MCP `archive_*`.
- **Obsidian:** scriere fișier `.md` pe disc — fără API Notion; utilizatorul sincronizează (iCloud/Git) dacă dorește.

## Extensii planificate

- **Notion API:** `NotionSink` cu `NOTION_TOKEN`, parent database/page id.
- **Google Drive:** export MD sau Google Docs API (complexitate + OAuth).
- **EPUB:** extragere capitol cu `ebooklib` + același pipeline de chunking.

## Securitate

- Token-uri Notion/Drive doar în `.env` sau secret manager; niciodată în repo.
- Path traversal: `subdirectory` sanitizat în `ObsidianVaultSink` (`..` eliminat).
