UV ?= uv
BACKEND_DIR := backend

.PHONY: run backend-sync backend-lock-check backend-migrate backend-migration-check backend-lint backend-format backend-typecheck backend-test backend-integration backend-coverage backend-smoke backend-check

run:
	cd $(BACKEND_DIR) && $(UV) run --locked uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-access-log

backend-sync:
	cd $(BACKEND_DIR) && $(UV) sync --extra dev

backend-lock-check:
	cd $(BACKEND_DIR) && $(UV) lock --check

backend-migrate:
	cd $(BACKEND_DIR) && $(UV) run --locked alembic upgrade head

backend-migration-check:
	cd $(BACKEND_DIR) && $(UV) run --locked python scripts/check_migrations.py

backend-lint:
	cd $(BACKEND_DIR) && $(UV) run --locked ruff check .

backend-format:
	cd $(BACKEND_DIR) && $(UV) run --locked ruff format --check .

backend-typecheck:
	cd $(BACKEND_DIR) && $(UV) run --locked mypy app tests

backend-test:
	cd $(BACKEND_DIR) && $(UV) run --locked pytest

backend-integration:
	$(if $(DATABASE_URL),,$(error DATABASE_URL is required for integration tests))
	cd $(BACKEND_DIR) && $(UV) run --locked pytest tests/test_rls.py tests/test_tenant_http_db.py

backend-coverage:
	$(if $(DATABASE_URL),,$(error DATABASE_URL is required for coverage))
	cd $(BACKEND_DIR) && $(UV) run --locked pytest --cov=app --cov-report=term-missing --cov-fail-under=80

backend-smoke:
	cd $(BACKEND_DIR) && $(UV) run --locked python scripts/smoke_http.py

backend-check: backend-lock-check backend-lint backend-format backend-typecheck backend-test
