#!/usr/bin/env bash
# Pornește API-ul din rădăcina proiectului (rezolvă „No module named 'app'” dacă rulai din ~).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${ROOT}/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  echo "Lipsește .venv. Rulează din acest folder:" >&2
  echo "  python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt" >&2
  exit 1
fi
exec "$PY" -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8090
