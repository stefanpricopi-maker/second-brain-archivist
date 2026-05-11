#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export LLM_MODE="${LLM_MODE:-disabled}"
export ANONYMIZED_TELEMETRY="${ANONYMIZED_TELEMETRY:-False}"
pip install -q -r requirements-dev.txt
mkdir -p data/library data/vectorstore
pytest tests/ -q --tb=short
