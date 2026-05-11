.PHONY: run ingest test
run:
	bash scripts/run_dev.sh

ingest:
	bash scripts/ingest.sh

test:
	@test -x .venv/bin/pytest && .venv/bin/pytest tests/ -q || pytest tests/ -q
