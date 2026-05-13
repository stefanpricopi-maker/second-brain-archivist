#!/usr/bin/env bash
# Pornește API-ul din rădăcina proiectului (rezolvă „No module named 'app'” dacă rulai din ~).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ROOT/.env"
  set +a
fi
PY="${ROOT}/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  echo "Lipsește .venv. Rulează din acest folder:" >&2
  echo "  python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt" >&2
  exit 1
fi
TLS_KEY="${SSL_KEYFILE:-$ROOT/data/tls/dev.key}"
TLS_CRT="${SSL_CERTFILE:-$ROOT/data/tls/dev.crt}"
UV_EXTRA=()
if [[ -f "$TLS_KEY" && -f "$TLS_CRT" ]]; then
  UV_EXTRA=(--ssl-keyfile "$TLS_KEY" --ssl-certfile "$TLS_CRT")
  echo "HTTPS: https://127.0.0.1:8090 (certificat din $TLS_CRT; cu mkcert ar trebui fără „Not secure” după «mkcert -install»)." >&2
else
  echo "HTTP: http://127.0.0.1:8090 — pentru HTTPS: bash scripts/generate_dev_tls_mkcert.sh (recomandat) sau bash scripts/generate_dev_tls.sh" >&2
fi
exec "$PY" -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8090 "${UV_EXTRA[@]}"
