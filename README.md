# Second Brain / Arhivistul (RAG + MCP)

Agent personal: **citești și întrebi** cărți (PDF), articole și notițe (Markdown) prin **RAG** (Chroma), apoi **salvezi sinteze** ca fișier descărcabil (deschizi link-ul în **Google Chrome**) sau extinzi spre **Notion / Google Drive** prin MCP.

## Rol în două propoziții

1. **RAG:** indexezi sute de fișiere din `data/library/` + notițe din `knowledge/public/`; `GET /search` și `POST /chat` folosesc același index.
2. **Arhivă:** `POST /archive/page` scrie un `.md` în `data/exports/` și returnează un link `GET /archive/files/...` pentru download (Chrome). Obsidian rămâne opțional dacă setezi `OBSIDIAN_VAULT_PATH`.

## Quick start

**Important:** `projects/second-brain-archivist` este relativ la repo-ul **agent-builder**. Mai întâi intră în folderul proiectului (altfel apar „no such file”, `requirements-dev.txt` negăsit, `No module named 'app'`).

```bash
# Exemplu (înlocuiește calea dacă ai repo-ul altundeva):
cd ~/dev/agent-builder/projects/second-brain-archivist

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
mkdir -p data/library data/vectorstore
# pune PDF/MD/TXT în data/library/ (și/sau knowledge/public/)
python scripts/ingest_library.py
uvicorn app.main:app --reload --host 127.0.0.1 --port 8090
```

**Fără activare venv** (tot din același folder proiect):

```bash
bash scripts/run_dev.sh
bash scripts/ingest.sh
```

- API: `http://127.0.0.1:8090/docs`
- UI: `http://127.0.0.1:8090/static/index.html` (ingest, **căutare RAG**, chat + voce, **arhivare .md** cu link, Drive: status / propunere / copiere)
- Dacă vezi **`No module named 'app'`**: nu ești în rădăcina proiectului sau folosești venv-ul altui proiect (ex. `audi-vcds-master`). `pwd` trebuie să fie `…/second-brain-archivist` (conține `app/`, `scripts/`).
- Chat fără OpenAI: în `.env` pune `LLM_MODE=disabled` — răspuns din fragmente RAG.
- Arhivare (Chrome): după `POST /archive/page`, deschide `path_or_url` în browser ca să descarci `.md`.
- Upload + „învață din documente”: `POST /ingest/files` (multipart) acceptă `.pdf`, `.txt`, `.md`, `.docx`. Pentru PDF-uri scanate: OCR nu e încă implementat (roadmap).

## MCP (Cursor / Claude Desktop)

```bash
python -m mcp_server.server
```

Unelte: `library_search`, `library_chunk_count`, `archive_save_markdown_page`, plus Drive: `drive_status`, `drive_library_folders`, `drive_propose_stage`, `drive_copy_items`. Vezi `spec/mcp-and-notion-v0.1.md` pentru Notion.

### Google Drive (Stage → bibliotecă)

1. Activează **Google Drive API** în Google Cloud; OAuth client **Desktop**; descarcă JSON-ul ca `data/drive/client_secret.json` (nu comite secretul).
2. În `.env`: `GOOGLE_DRIVE_STAGE_FOLDER_ID`, `GOOGLE_DRIVE_LIBRARY_ROOT_FOLDER_ID` (ID din URL `.../folders/<ID>`).
3. `python scripts/drive_auth.py` — deschide browserul, salvează `data/drive/token.json`.
4. API: `GET /drive/status`, `GET /drive/folders`, `POST /drive/propose`, `POST /drive/copy` cu `{"items":[...], "ingest_to_rag": true}` — **copiere** (originalul rămâne în Stage); dacă `ingest_to_rag` e true, după copiere fișierul e descărcat din bibliotecă și adăugat în **Chroma**. În UI, bifă „indexează în RAG”. După `GOOGLE_DRIVE_MIN_AUTO` confirmări (implicit 2), `propose` poate marca `needs_user: false` când LLM-ul e activ (`LLM_MODE=openai`).

## Structură (kit)

| Path | Rol |
|------|-----|
| `app/main.py` | FastAPI: health, search, chat, archive |
| `app/rag.py` | Chroma `second_brain_library` |
| `app/connectors/` | Download (Chrome) + Obsidian opțional + stub |
| `scripts/ingest_library.py` | PDF + MD + TXT (EPUB = roadmap) |
| `mcp_server/server.py` | MCP FastMCP |
| `spec/` | Definiție agent, arhitectură, plan teste, integrări |

## Confidențialitate

Datele tale rămân **local** (disc + vector store). Notion/Drive implică **token** și politica furnizorului — documentează înainte de activare.

## Repo GitHub dedicat (split din monorepo)

CI: `.github/workflows/ci.yml` (pytest pe Python 3.12). Dependabot: `.github/dependabot.yml` (pip + GitHub Actions). Versiune locală Python: `.python-version`.

### 1) Primul commit în acest folder

```bash
cd /path/to/second-brain-archivist   # rădăcina proiectului (conține app/, README.md)
git init -b main
git add -A
git status    # verifică că nu intră .venv/, data/*, .env
git commit -m "Initial commit: second-brain-archivist"
```

### 2) Creează repo gol pe GitHub și împinge

```bash
# variantă GitHub CLI:
gh repo create second-brain-archivist --private --source=. --remote=origin --push

# sau manual: creează repo gol pe github.com, apoi:
git remote add origin https://github.com/<USER>/second-brain-archivist.git
git push -u origin main
```

### 3) Dacă folderul încă stă în interiorul repo-ului `agent-builder`

Ca să nu ai două repouri Git care se calce pe același copac de fișiere, în **rădăcina `agent-builder`** adaugă în `.gitignore`:

```gitignore
projects/second-brain-archivist/
```

Apoi nu mai versiona acel subfolder în monorepo; lucrezi doar din clone-ul / folderul cu `git init` de mai sus.
