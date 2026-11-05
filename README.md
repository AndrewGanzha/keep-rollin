# План реализации MVP: контракт → FastAPI → Nuxt (Vue 3)

> Часть плана MVP. Навигация: [README](README.md) · [Контракт](docs/contract/README.md) · [API](docs/contract/api.md) · [Модель данных](docs/contract/data-model.md) · [Задачи](docs/tasks/README.md) · [Поставка](docs/delivery.md)

**Источник требований:** [use-cases.md](use-cases.md) (далее «ТЗ»).
**Что меняется относительно ТЗ:** Приложение C (стек) заменено на **Vue 3 (Nuxt 4) + FastAPI**; вместо «списка эндпоинтов» вводится **обязательный контракт** (OpenAPI 3.1) как артефакт с гейтами в CI.
**Порядок работ:** контракт → фронтенд на моке → backend (§2.1). UI начинается сразу после появления операции в снапшоте.

---

## Карта документов

| Файл | Содержимое |
| ---- | ---------- |
| [`docs/contract/README.md`](docs/contract/README.md) | §2 процесс contract-first и гейты CI, §2.1 frontend-first на моке; §3 сквозные решения: тенант, auth/2FA, роли, ошибки, идемпотентность, занятость, лимиты, enum-ы, уведомления, метрики |
| [`docs/contract/api.md`](docs/contract/api.md) | §4 каталог эндпоинтов по доменам |
| [`docs/contract/data-model.md`](docs/contract/data-model.md) | §5 изменения модели данных относительно ТЗ |
| [`docs/tasks/README.md`](docs/tasks/README.md) | §6 индекс задач и подгруппы, §6.5 фазы и гейты, §7 порядок/параллельность, §8 DoR/DoD |
| [`docs/tasks/contract.md`](docs/tasks/contract.md) | §6.1 контракт — CT-01…CT-09 (включая stateful mock) |
| [`docs/tasks/backend.md`](docs/tasks/backend.md) | §6.2 backend — 54 задачи (B1…B11) |
| [`docs/tasks/frontend.md`](docs/tasks/frontend.md) | §6.3 frontend — 44 задачи (F1…F11) |
| [`docs/tasks/qa.md`](docs/tasks/qa.md) | §6.4 окружение и приёмка — QA-00, QA-01 |
| [`docs/delivery.md`](docs/delivery.md) | §9 решения по открытым вопросам ТЗ, §10 риски, §11 трассировка UC → задачи |
| [`deploy/README.md`](deploy/README.md) | Деплой Nuxt-фронтенда в k3s: образ, манифесты, `deploy.sh`, CI и откат |

Нумерация `§` сквозная по всем файлам: `§3.8` означает один и тот же раздел в любом файле.

`docs/` — только план. Каталог `contract/` зарезервирован под артефакты контракта (`decisions.md`, `endpoints.md`, `openapi.json`, `analytics.md`, `pricing.md`), которые создают CT-01/CT-02.

## 1. Стек и границы

### 1.1. Frontend

| Слой               | Решение                                                              | Причина                                                                       |
| ------------------ | -------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| Фреймворк          | **Nuxt 4 (Vue 3.5, TypeScript strict)**                              | ТЗ требует SSR для гостевых страниц (SEO) + быстрый TTFB на 3G; SPA-разделы — тем же приложением |
| UI                 | **PrimeVue 4.5** (+ `@primevue/themes`, `primelocale`)               | Единственная UI-библиотека во фронтенде; брендинг тенанта через CSS-переменные |
| Состояние          | **Pinia** — сессия, тенант, UI; `useAsyncData`/`useFetch` — серверные данные | Не тащим второй кэш-слой (TanStack Query) в SSR-приложение                     |
| API-клиент         | **openapi-typescript + openapi-fetch** из `contract/openapi.json`    | Типы и клиент генерируются из контракта, руками не пишутся                    |
| Mock API           | **mock-config-server** (`mock-server.config.ts`)                     | Один конфиг отвечает по путям контракта; работает без backend                 |
| Формы/валидация    | PrimeVue-формы + серверная валидация; zod — по мере роста             | Не плодим слой валидации раньше контракта                                     |
| i18n               | ru-локаль PrimeVue; интерфейс на русском                              | ТЗ 9.5: один язык в MVP; `vue-i18n` подключается при необходимости            |
| PWA                | `@vite-pwa/nuxt` (manifest, SW, Web Push)                             | iOS push возможен только в установленной PWA (ТЗ 9.4)                          |
| Тесты              | Vitest (unit); Playwright — на этапе e2e                              | Сначала быстрый фидбек, e2e — после стабилизации сценариев                    |

### 1.2. Backend

| Слой            | Решение                                                                 |
| --------------- | ----------------------------------------------------------------------- |
| Runtime         | Python 3.12, FastAPI, Pydantic v2 (источник OpenAPI)                     |
| ORM/БД          | SQLAlchemy 2 (async) + asyncpg, Alembic, **PostgreSQL 16** + RLS + `btree_gist` |
| Фоновые задачи  | Отдельный контейнер `worker`: APScheduler (cron) + outbox-consumer на `FOR UPDATE SKIP LOCKED` |
| Файлы           | S3-совместимое (MinIO в dev): публичный бакет (фото лотов) + приватный (документы) |
| Email / Push    | SMTP (MailHog в dev) / SES; `pywebpush` + VAPID per tenant              |
| Наблюдаемость   | Sentry SDK, structured JSON logs, `/metrics` (Prometheus)               |
| Тесты           | pytest + pytest-asyncio + polyfactory; **schemathesis** для контракта    |

**Сознательно не берём в MVP:** Redis (rate limiting — in-process, outbox — на Postgres), Celery, GraphQL, schema-per-tenant, платформенный API (провижининг тенантов — CLI, см. §9).

### 1.3. Монорепо

```
/
  README.md            # план: стек, карта документов
  use-cases.md         # ТЗ
  docs/                # план: contract/ (решения, API, данные), tasks/, delivery.md
  contract/            # openapi.json (seed) + артефакты: decisions.md, endpoints.md, analytics.md, pricing.md
  frontend/            # Nuxt 4: app/{pages,widgets,features,entities,shared}, mock-server.config.ts
  backend/             # (появляется на BE-00)
  docker-compose.yml   # postgres, minio, mailhog, api, worker, web
  Makefile             # up, seed, openapi, gen, contract-check, mock, test
```

### 1.4. Нужно от заказчика до старта P2

Текст оферты, лого/цвета/домены тенанта, доступы SMTP/SES и S3, юридическое решение по сроку хранения паспортных документов (см. §9 Q4), подтверждение модели «custom» (см. D-12).
