#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${ROOT}/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  echo "Lipsește .venv. Creează-l și instalează requirements-dev.txt" >&2
  exit 1
fi
exec "$PY" scripts/ingest_library.py
