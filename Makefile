UV ?= uv
BACKEND_DIR := backend

.PHONY: run backend-sync backend-lock-check backend-lint backend-format backend-typecheck backend-test backend-smoke backend-check

run:
	cd $(BACKEND_DIR) && $(UV) run --locked uvicorn app.main:app --host 0.0.0.0 --port 8000

backend-sync:
	cd $(BACKEND_DIR) && $(UV) sync --extra dev

backend-lock-check:
	cd $(BACKEND_DIR) && $(UV) lock --check

backend-lint:
	cd $(BACKEND_DIR) && $(UV) run --locked ruff check .

backend-format:
	cd $(BACKEND_DIR) && $(UV) run --locked ruff format --check .

backend-typecheck:
	cd $(BACKEND_DIR) && $(UV) run --locked mypy app tests

backend-test:
	cd $(BACKEND_DIR) && $(UV) run --locked pytest

backend-smoke:
	cd $(BACKEND_DIR) && $(UV) run --locked python scripts/smoke_http.py

backend-check: backend-lock-check backend-lint backend-format backend-typecheck backend-test
