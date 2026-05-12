# Second Brain / Arhivistul (RAG + MCP)

Agent personal: **citești și întrebi** cărți (PDF), articole și notițe (Markdown) prin **RAG** (Chroma), apoi **salvezi sinteze** ca fișier descărcabil (deschizi link-ul în **Google Chrome**) sau extinzi spre **Notion / Google Drive** prin MCP.

## Rol în două propoziții

1. **RAG:** indexezi sute de fișiere din `data/library/` + notițe din `knowledge/public/`; `GET /search` și `POST /chat` folosesc același index.
2. **Arhivă:** `POST /archive/page` — **Obsidian** dacă `OBSIDIAN_VAULT_PATH`; altfel **Notion** dacă `NOTION_TOKEN` + parent (pagină sau bază de date); altfel `.md` în `data/exports/` + link `GET /archive/files/...` (Chrome).

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
- UI: `http://127.0.0.1:8090/static/index.html` — tab-uri (Index, Căutare, Chat, Arhivă, **Cărți & voce**, Drive, Serviciu). **Cărți & voce** (separat de Drive): PDF scanat → OCR local (Tesseract) → index RAG; alegi cartea din listă; **întrebare vocală** + **răspuns citit** în browser (Chrome). **Drive** — wizard în 3 pași: conexiune → încărcare în Stage (`POST /drive/stage/upload`) → **plasare automată** (`POST /drive/wizard/auto-place`, max. 120 ID-uri/cerere; UI împarte automat listele mai lungi în mai multe cereri), după extensie; la nevoie, listă + dropdown pentru remedieri manuale. „Drive avansat” pentru bulk din Stage.
- Dacă vezi **`No module named 'app'`**: nu ești în rădăcina proiectului sau folosești venv-ul altui proiect (ex. `audi-vcds-master`). `pwd` trebuie să fie `…/second-brain-archivist` (conține `app/`, `scripts/`).
- Chat fără OpenAI: în `.env` pune `LLM_MODE=disabled` — răspuns din fragmente RAG.
- Arhivare: după `POST /archive/page`, `path_or_url` poate fi link Notion, cale Obsidian, sau URL relativ pentru download (Chrome).
- Upload + „învață din documente”: `POST /ingest/files` (multipart) acceptă `.pdf`, `.epub`, `.txt`, `.md`, `.docx`. Pentru **PDF-uri scanate** folosește tab-ul **Cărți & voce** sau `POST /voice-library/ingest` (OCR cu **Tesseract** + **poppler**). **macOS:** `brew install tesseract tesseract-lang poppler` — `tesseract-lang` aduce limbi suplimentare, inclusiv **română (`ron`)**. OCR implicit e **română** (`OCR_LANG=ron` în cod); pentru pagini cu mult engleză pune în `.env` `OCR_LANG=ron+eng`. Dacă „OCR indisponibil” persistă, repornește serverul din terminal sau setează în `.env` căile Homebrew (IDE-ul poate avea PATH restrâns): `TESSERACT_CMD=/opt/homebrew/bin/tesseract` și `POPPLER_PATH=/opt/homebrew/bin` (Apple Silicon; pe Intel adesea `/usr/local/bin`). **Ubuntu:** `apt install tesseract-ocr tesseract-ocr-ron poppler-utils` (+ opțional `tesseract-ocr-eng`). Opțional: `OCR_DPI=200`.

## MCP (Cursor / Claude Desktop)

```bash
python -m mcp_server.server
```

Unelte: `library_search`, `library_chunk_count`, `archive_save_markdown_page`, `notion_create_page` (doar Notion), plus Drive: `drive_status`, `drive_library_folders`, `drive_propose_stage`, `drive_copy_items`, `drive_wizard_auto_place` (plasare automată cu chunking la fel ca API-ul). Vezi `spec/mcp-and-notion-v0.1.md`.

### Google Drive (Stage → bibliotecă)

1. Activează **Google Drive API** în Google Cloud; OAuth client **Desktop**; descarcă JSON-ul ca `data/drive/client_secret.json` (nu comite secretul).
2. În `.env`: `GOOGLE_DRIVE_STAGE_FOLDER_ID`, `GOOGLE_DRIVE_LIBRARY_ROOT_FOLDER_ID` (ID din URL `.../folders/<ID>`).
3. `python scripts/drive_auth.py` — deschide browserul, salvează `data/drive/token.json`.
4. API: `GET /drive/status`, `GET /drive/folders`, `POST /drive/stage/upload` (multipart `files`), `POST /drive/propose`, `POST /drive/copy` cu `{"items":[...], "ingest_to_rag": true}` — **copiere** (originalul rămâne în Stage); dacă `ingest_to_rag` e true, după copiere fișierul e descărcat din bibliotecă și adăugat în **Chroma**. Opțional `GOOGLE_DRIVE_STAGE_FOLDER_URL` — link deschis din UI la folderul Stage. După `GOOGLE_DRIVE_MIN_AUTO` confirmări (implicit 2), `propose` poate marca `needs_user: false` când LLM-ul e activ (`LLM_MODE=openai`).
5. **Subfoldere după extensie (implicit):** la `POST /drive/propose`, dacă `GOOGLE_DRIVE_THEME_PATHS` nu e dezactivat, pentru fiecare fișier se folosește **doar extensia**: `.pdf` → folder **PDF**, `.doc`/`.docx` → **Documente**, `.png`/`.jpeg`/`.jpg` → **Afise**, `.ppt`/`.pptx` → **Powerpoint**, altceva → **Altele**. Folderele lipsă sunt create sub `GOOGLE_DRIVE_LIBRARY_ROOT_FOLDER_ID`. Dezactivare: `GOOGLE_DRIVE_THEME_PATHS=false` (rămâne doar sugestia între folderele deja existente sub rădăcină).
6. **Batch fără UI (mii de fișiere):** `POST /drive/batch/auto-organize` cu JSON `{"source_folder_id":"…"}` (sau omis = folder Stage), `recursive`, `max_files` (max 500 per cerere), `ingest_to_rag`, `pause_sec` — citește fișier cu fișier, sare peste ID-urile deja copiate (memorie), copiază în subfolderul după extensie. Pentru volume mari rulează din terminal: `python scripts/drive_batch_auto_organize.py` (implicit până la 50 000 fișiere, opțiuni `--recursive`, `--ingest-rag`, `--dry-run`). Raport: `data/drive/batch_last_report.json`.
7. **Wizard după upload:** `POST /drive/wizard/auto-place` cu `{"source_file_ids":["…"],"ingest_to_rag":false}` — max. 120 ID-uri per cerere (server); UI-ul trimite automat mai multe cereri dacă lista e mai lungă. Pentru mii de fișiere deja în Stage, folosește `python scripts/drive_batch_auto_organize.py`.

## Structură (kit)

| Path | Rol |
|------|-----|
| `app/main.py` | FastAPI: health, search, chat, ingest, voice-library (OCR), archive, Drive |
| `app/ocr_pdf.py` | OCR PDF (Tesseract + pdf2image) |
| `app/rag.py` | Chroma `second_brain_library` |
| `app/connectors/` | Download (Chrome), Obsidian, Notion API |
| `scripts/ingest_library.py` | PDF + EPUB + MD + TXT în `data/library/` |
| `mcp_server/server.py` | MCP FastMCP |
| `spec/` | Definiție agent, arhitectură, plan teste, integrări |

## Confidențialitate

Datele tale rămân **local** (disc + vector store). Notion/Drive implică **token** și politica furnizorului — documentează înainte de activare.

## Hardening (operare)

- **Request ID**: răspunsul include `X-Request-ID` (poți trimite același header la intrare); logurile pe stdout folosesc `LOG_LEVEL` și prefix `[rid=…]` (`app/logging_setup.py`).
- **Rate limit**: per IP, în memorie, separat GET vs POST (`RATE_LIMIT_GET_PER_MINUTE`, `RATE_LIMIT_POST_PER_MINUTE`). Dezactivare: `RATE_LIMIT_ENABLED=false` (implicit în `tests/conftest.py` și în CI).
- **Path traversal**: `GET /archive/files/…` și subdirectoarele pentru arhivă (Obsidian / export) folosesc validare strictă (`app/path_security.py`).
- **Static UI**: `Cache-Control: public, max-age=3600` pentru `/static/`.
- **Teste**: `pytest` cu `--timeout=120` (vezi `requirements-dev.txt` + `pytest.ini`).

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
