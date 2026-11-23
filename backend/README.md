# Backend (FastAPI)

Каркас backend для BE-00…BE-03. Сервис содержит инфраструктурные
`GET /health` и `GET /readyz`, request context, problem+json, JSON access logs,
tenant resolution по Host, SQLAlchemy/Alembic и RLS-изоляцию `tenant`/`user`.
Бизнес-эндпоинты появляются в следующих задачах.

## Требования

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- PostgreSQL 16 (в CI поднимается сервисом; локально подойдёт PostgreSQL 15)

На Windows без установленного `uv` можно использовать `py -3.12 -m uv`.

## Запуск

```powershell
cd backend
uv sync --extra dev
Copy-Item .env.example .env
uv run --locked alembic upgrade head
uv run --locked uvicorn app.main:app --reload --no-access-log
```

`DATABASE_URL` — DSN администратора/миграций. Внутри транзакции приложение
выполняет `SET LOCAL ROLE keep_rollin_app`, поэтому RLS работает даже при
локальном admin-DSN. В production приложение должно подключаться отдельным
логином с минимальными правами и членством в `keep_rollin_app`.

Основные переменные:

| Переменная | Назначение |
| --- | --- |
| `DATABASE_URL` | PostgreSQL DSN |
| `DATABASE_ROLE` | роль для `SET LOCAL ROLE`, по умолчанию `keep_rollin_app` |
| `PLATFORM_DOMAIN` | домен платформы для поиска поддоменов |
| `ALLOW_TENANT_HEADER` | `X-Tenant` только для local/test |

Без `DATABASE_URL` приложение запускается, `/health` отвечает `200`, а `/readyz`
честно отвечает `503`.

## Миграции и RLS

```powershell
$env:DATABASE_URL = "postgresql://postgres:postgres@127.0.0.1:5432/keep_rollin"
uv run --locked alembic upgrade head
uv run --locked python scripts/check_migrations.py
```

`check_migrations.py` создаёт временную БД, прогоняет
`upgrade head -> downgrade base -> upgrade head` и удаляет её. Роль
`keep_rollin_app` кластерная и при downgrade не удаляется.

Политики RLS используют `NULLIF(current_setting('app.tenant_id', true), '')::uuid`.
`resolve_tenant(host, kind)` — узкая `SECURITY DEFINER` функция для поиска
тенанта по домену или поддомену.

## Проверки

```powershell
$env:DATABASE_URL = "postgresql://postgres:postgres@127.0.0.1:5432/keep_rollin"
uv lock --check
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy app tests
uv run --locked pytest
uv run --locked pytest --cov=app --cov-report=term-missing --cov-fail-under=80
uv run --locked python scripts/smoke_http.py --expect-ready
```

Без `DATABASE_URL` интеграционные тесты и RLS-проверки помечаются `skipped`;
порог покрытия и приёмка BE-03 требуют PostgreSQL.

Smoke с реальной базой:

```powershell
$env:DATABASE_URL = "postgresql://postgres:postgres@127.0.0.1:5432/keep_rollin"
uv run --locked python scripts/smoke_http.py --expect-ready
```

Из корня репозитория доступны `make run`, `make backend-check`
(lock, Ruff, format, mypy, pytest), `make backend-integration`,
`make backend-coverage`, `make backend-smoke` и `make backend-migration-check`,
если установлен `make` и `uv` есть в `PATH`. Цели coverage/integration требуют
`DATABASE_URL`.

## Каталог: слои

Публичный каталог добавлен по принципам backend-шаблона:

```text
src/
  domain/           # Category, Characteristic, Lot, LotVariant, value objects
  application/      # DTOs, repository ports, query handlers
  infrastructure/
    postgres/       # SQLAlchemy records и repository implementations
app/api/            # тонкие HTTP-роутеры и FastAPI-wiring
```

Правила:

- `domain` не импортирует FastAPI, SQLAlchemy или `app`;
- repository ports возвращают domain entities;
- DTO собираются через `from_domain(...)`;
- роутеры не содержат SQL и бизнес-правил;
- RLS включён на всех таблицах каталога, `tenant_id` денормализован в дочерние таблицы;
- публичные ответы остаются в формате `contract/openapi.json` (без envelope шаблона);
- для этого среза используется FastAPI `Depends`, так как request-scoped сессией владеет `TenantMiddleware`; Dishka можно добавить позже без изменения domain/application.

Публичные endpoint:

```text
GET /api/v1/public/categories
GET /api/v1/public/lots?category_id=&q=&limit=&offset=
GET /api/v1/public/lots/{slug}
```

Админские CRUD-операции каталога отложены до появления собственной авторизации.

## Известные ограничения MVP

- Настоящий streaming с долгоживущей БД-сессией не поддерживается: тело ответа
  буферизуется, транзакция завершается до отправки. Для streaming-эндпоинта нужен
  отдельный lifecycle.
- Интеграционные тесты используют общую БД из `DATABASE_URL`, создают уникальные
  данные и удаляют их в teardown; CI поднимает одноразовый PostgreSQL 16.
- Поддержаны основные TLS-параметры (`sslmode`, `sslrootcert`, `sslcert`,
  `sslkey`, `sslpassword`, min/max TLS, `PGSSL*`). Неподдерживаемые комбинации
  (`sslcrl`, `sslnegotiation`, TLS-параметры с `allow`/`prefer`) отклоняются.
