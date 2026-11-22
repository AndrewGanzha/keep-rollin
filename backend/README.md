# Backend (FastAPI)

Каркас backend для BE-00. В этом срезе есть только инфраструктурные эндпоинты:
`GET /health` и `GET /readyz`. Бизнес-эндпоинты, middleware, БД-модели и миграции
появляются в следующих задачах.

## Требования

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- PostgreSQL 16 для проверки readiness (в CI поднимается сервисом)

На Windows без установленного `uv` можно использовать `py -3.12 -m uv`.

## Запуск

```powershell
cd backend
uv sync --extra dev
Copy-Item .env.example .env
uv run --locked uvicorn app.main:app --reload
```

Без `DATABASE_URL` приложение запускается, `/health` отвечает `200`, а `/readyz`
честно отвечает `503` — база ещё не подключена.

## Проверки

```powershell
uv lock --check
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy app tests
uv run --locked pytest
uv run --locked python scripts/smoke_http.py
```

Smoke с реальной базой:

```powershell
$env:DATABASE_URL = "postgresql://postgres:postgres@127.0.0.1:5432/keep_rollin"
uv run --locked python scripts/smoke_http.py --expect-ready
```

Из корня репозитория доступны `make run`, `make backend-check`
(lock, Ruff, format, mypy, pytest) и `make backend-smoke` (HTTP smoke без БД),
если установлен `make` и `uv` есть в `PATH`.
