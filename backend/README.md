# Backend (FastAPI)

Backend keep-rollin: FastAPI, SQLAlchemy/Alembic, tenant RLS, публичный каталог,
доступность и расчёт цены, auth-core, админские категории, настройки и оферты.
Сервис содержит `GET /health` и `GET /readyz`, request context, problem+json,
JSON access logs и tenant resolution по Host.

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
| `JWT_SECRET` | секрет access JWT; в production обязателен |
| `ACCESS_TTL_SECONDS` | TTL access JWT, по умолчанию 900 |
| `REFRESH_TTL_DAYS` | TTL refresh-сессии, по умолчанию 30 |
| `PASSWORD_WORK_TIMEOUT_SECONDS` | максимум ожидания слота Argon2, по умолчанию 5 |
| `REFRESH_COOKIE_NAME` | имя refresh-cookie, в production `__Host-rt` |
| `REFRESH_COOKIE_SECURE` | `Secure` для refresh-cookie; в production только `true` |

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
uv run --locked mypy app src tests
uv run --locked pytest
uv run --locked pytest --cov=app --cov=src --cov-report=term-missing --cov-fail-under=80
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
GET /api/v1/public/tenant
GET /api/v1/public/categories
GET /api/v1/public/lots?category_id=&q=&limit=&offset=
GET /api/v1/public/lots/{slug}
GET /api/v1/public/lots/{slug}/availability?from=&to=
GET /api/v1/public/lots/{slug}/quote?start=&end=
```

## Авторизация

Реализован auth-core:

```text
POST /api/v1/auth/register
POST /api/v1/auth/login
POST /api/v1/auth/refresh
POST /api/v1/auth/logout
GET  /api/v1/auth/session
```

- регистрация принимает `email`, `password`, опциональные `phone` и `name`
  (без `name` берётся локальная часть email); пароль — argon2id, email
  нормализуется и уникален в тенанте;
- MVP-список распространённых утёкших паролей отклоняется с 422; полная
  интеграция HIBP k-anonymity — отдельная задача;
- хеширование и проверка пароля выполняются в bounded thread pool, dummy-hash
  переиспользуется process-wide;
- access JWT: 15 минут, claims `sub/tnt/role/ver/jti/exp`;
- refresh — opaque 30 дней в `__Host-rt` (`HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/`);
- refresh ротируется, повторное использование отзывает всю family; ротация,
  reuse-revoke и logout сериализуются advisory-lock по family;
- `GET /auth/session` проверяет `tnt` от Host, `is_active` и `token_version`;
- RBAC-матрица owner/admin/user и `require_permission` готовы для admin-роутов;
- CSRF guard требует `Origin` и `Sec-Fetch-Site` для небезопасных
  auth-запросов, проверяет scheme/host/port и отклоняет неканонический Origin.
  API-клиенты должны отправлять оба заголовка; для не-браузерных вызовов
  `Sec-Fetch-Site: none`.

MFA, password reset, rate limit и полная проверка утечек остаются отдельными
задачами. `phone` опционален для MVP; `offer_accepted` уже отражает принятие
текущей active-оферты, а `prefs-summary` появится вместе с настройками
уведомлений.
В production обязательны непустой `JWT_SECRET`, cookie `__Host-rt`
и `Secure=True`; dev-secret запрещён. Образ Docker выставляет
`APP_ENV=production`, поэтому без `JWT_SECRET` контейнер не стартует.
За TLS-прокси задайте `FORWARDED_ALLOW_IPS` для uvicorn (образ уже включает
`--proxy-headers`), чтобы `request.url.scheme` и CSRF-проверка Origin видели
публичную схему. Доверять `X-Forwarded-Proto` без allowlist нельзя.

## Админ-категории

```text
GET   /api/v1/admin/categories?include_archived=&limit=&offset=
POST  /api/v1/admin/categories
PATCH /api/v1/admin/categories/{id}
```

- доступ только для `owner` (`catalog.manage`); admin/user получают 403;
- admin-DTO содержит `version` и все характеристики, включая архивные
  (`is_archived=true`); публичный DTO не изменён и отдаёт только активные;
- `POST` валидирует name/slug/description и отклоняет дубль slug с 409 `slug_taken`;
- `PATCH` требует `version`, при устаревшей версии возвращает 409 `stale_version`;
- архивация скрывает категорию и её лоты из публичного каталога;
- миграция `0007_category_version` добавляет `category.version >= 1`.

Bulk-характеристики:

```text
PUT /api/v1/admin/categories/{id}/characteristics
```

- требует `category.version`; успех увеличивает версию категории;
- `code` неизменяем, определения создаются/обновляются/архивируются;
- `number`/`text` без options, `select` требует непустой уникальный список;
- смена типа при наличии значения в `lot.characteristics` → 409 `characteristic_in_use`;
- архивные определения видны в admin-DTO, но скрыты из публичного каталога.

## Настройки тенанта

```text
GET   /api/v1/admin/settings
PATCH /api/v1/admin/settings
```

- owner-only (`settings.manage`), `no-store`;
- PATCH требует `version` и валидирует диапазоны §3.8, IANA timezone,
  ISO-подобный currency, hex-цвет и http(s) logo URL;
- частичный `policies` мержится с текущими значениями, stale version → 409;
- `timezone`/`currency` обновляются в `tenant`, брендинг и политики — в
  `tenant_settings`; публичный `/public/tenant` сразу отражает изменения.

## Оферты

```text
GET  /api/v1/public/offers/current
GET  /api/v1/admin/offers
POST /api/v1/admin/offers
PATCH /api/v1/admin/offers/{id}
POST /api/v1/admin/offers/{id}/publish
GET  /api/v1/me/offer-acceptances
POST /api/v1/me/offer-acceptances
```

- owner-only управление (`offers.manage`), draft можно править, active/archived — нет;
- публикация атомарно архивирует предыдущую active-версию; partial unique index
  гарантирует ровно одну active-версию на тенант;
- принятие возможно только для active-версии, повтор идемпотентен и фиксирует
  версию, время и IP;
- `GET /auth/session` возвращает `offer_accepted=true` только после принятия
  текущей active-версии; новая публикация сбрасывает флаг до повторного принятия.

## Админ-календарь и блокировки

```text
GET    /api/v1/admin/calendar?from=&to=&category_id=&lot_id=&status=
GET    /api/v1/admin/lots/{id}/calendar?from=&to=
POST   /api/v1/admin/lots/{id}/blocks
DELETE /api/v1/admin/lots/{id}/blocks/{block_id}
```

- доступ: `calendar.view` / `calendar.block` (owner и admin), user → 403;
- окно календаря ограничено 90 днями, ответы `no-store`, фильтр шире 200 лотов → 422;
- событие содержит `kind`, `rental_id` или `block_id`, `status`, времена и `reason`;
- booking-события отдают статус `booked`; block/maintenance — статус occupancy;
- границы блока выравниваются по локальной полуночи tenant (хранение в UTC);
- блок требует причину 3–200 символов и автора, пересечение с active occupancy → 409 `slot_taken`;
- удаление блока освобождает интервал; повторное удаление идемпотентно, неизвестный блок → 404.

Audit-запись блокировок остаётся в BE-VER-04; аренды/rental status появятся в BE-BOOK-01.

## Занятость и цена

`occupancy` хранит интервалы `[start, end)` с `tenant_id`, tenant-safe FK на лот
и PostgreSQL `EXCLUDE USING gist` для активных пересечений. `reserve`/`release`
реализованы сервисными примитивами: пересечение даёт `OccupancyConflictError`,
повторный `release` идемпотентен. Публичная доступность маскирует внутренние
типы занятости как `busy` и возвращает `next_free`; диапазон больше 90 дней
отклоняется.

`quote` реализует D-20: округление длительности вверх, минимальную допустимую
длительность, выбор тарифа и round-up к более дешёвому длинному тарифу. Валюта
берётся из tenant; `battery_unavailable` не вычисляется, пока нет `battery_stock`.

`GET /public/tenant` отдаёт публичный branding, timezone, currency, VAPID key и
policies из `tenant_settings` с `Cache-Control: max-age=300`. Админский
`GET/PATCH /admin/settings` реализован: PATCH использует `version`, валидирует
диапазоны §3.8 и сразу отражается в публичном ответе.

## Outbox

`outbox_message` хранит события в транзакции писателя. `OutboxWriter` только
добавляет pending-сообщение и не коммитит. `OutboxConsumer` забирает due-события
через `FOR UPDATE SKIP LOCKED`, вызывает handler и делает retry через 1/5/15 минут,
после чего переводит событие в `failed`. `NoopOutboxHandler` используется до
подключения email/push-провайдеров. Уникальность цепочки
`(event_type, entity_id, user_id, channel)` tenant-scoped и использует
`NULLS NOT DISTINCT`.

Админские категории, настройки и оферты уже реализованы. CRUD лотов, ручные
блокировки, аренды, верификация, тикеты и остальные админ-сценарии остаются
следующими задачами.

## Известные ограничения MVP

- Настоящий streaming с долгоживущей БД-сессией не поддерживается: тело ответа
  буферизуется, транзакция завершается до отправки. Для streaming-эндпоинта нужен
  отдельный lifecycle.
- Интеграционные тесты используют общую БД из `DATABASE_URL`, создают уникальные
  данные и удаляют их в teardown; CI поднимает одноразовый PostgreSQL 16.
- Поддержаны основные TLS-параметры (`sslmode`, `sslrootcert`, `sslcert`,
  `sslkey`, `sslpassword`, min/max TLS, `PGSSL*`). Неподдерживаемые комбинации
  (`sslcrl`, `sslnegotiation`, TLS-параметры с `allow`/`prefer`) отклоняются.


## Загрузка файлов и очистка

Для загрузок настройте `S3_PUBLIC_BUCKET`, `S3_PRIVATE_BUCKET` и `S3_PUBLIC_BASE_URL`. Публичный URL должен вести к корню публичного бакета или CDN над ним. `S3_ENDPOINT_URL` задаётся для S3-совместимого хранилища и должен быть доступен получателям подписанных ссылок. Для AWS достаточно региона `S3_REGION`. Учетные данные SDK берёт из штатной цепочки AWS. Приватный бакет держите закрытым для анонимного чтения, публичному бакету или CDN разрешите выдавать фото лотов.

`python -m app.cli purge-orphan-uploads` показывает число непривязанных загрузок старше 24 часов. `--execute` удаляет их из хранилища и БД. Команда использует `PROVISION_DATABASE_URL`, конфигурацию тех же бакетов и роль с правом удалять объекты. Привязанные файлы сохраняются. Если удаление прерывается, следующий запуск продолжает обработку. Расписание запуска относится к BE-WRK-04.
