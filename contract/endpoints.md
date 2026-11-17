# Эндпоинты CR-01

> Контракт: [README](README.md) · [openapi.json](openapi.json) · [pricing.md](pricing.md) · [decisions.md](decisions.md)
> Полный каталог MVP — [`../docs/contract/api.md`](../docs/contract/api.md); здесь только операции, добавленные
> или изменённые CR-01. Источник правды — `contract/openapi.json`.

## 1. Новые операции

| Метод и путь | Роли | Назначение | Коды ответов |
| ------------ | ---- | ---------- | ------------ |
| `GET /api/v1/public/lots/{slug}/quote` | гость | Цена и доступность каждого варианта на `[start, end)` | `200`, `404`, `422` (`validation_error`, `rental_period_not_allowed`) |
| `PATCH /api/v1/admin/lots/{id}` | owner | Правка лота, вариантов, тарифов, сроков; требует `version` | `200`, `401`, `403`, `404`, `409` (`stale_version`), `422` |
| `POST /api/v1/admin/lots/{id}/blocks` | admin, owner | Блокировка дней лота | `201`, `401`, `403`, `404`, `409` (`slot_taken`), `422` |
| `DELETE /api/v1/admin/lots/{id}/blocks/{block_id}` | admin, owner | Снятие блокировки | `204`, `401`, `403`, `404` |
| `GET /api/v1/admin/schedule` | admin, owner | Гант «лоты × дни»: лоты без событий, аренды, блоки, остатки АКБ | `200`, `401`, `403`, `422` (окно > 90 дней) |
| `GET /api/v1/admin/batteries` | owner | Остатки АКБ по типам | `200`, `401`, `403` |
| `PATCH /api/v1/admin/batteries/{battery_type}` | owner | Изменение количества АКБ типа | `200`, `401`, `403`, `404`, `409` (`stock_below_committed`), `422` |

`GET /public/lots/{slug}/quote` и `GET /admin/schedule` объявлены `Cache-Control: no-store`: ответ зависит от
интервала, броней и блоков. Оба помечены заголовком в `openapi.json`.

## 2. Изменённые операции и DTO

| Операция / DTO | Что изменилось |
| -------------- | -------------- |
| `Lot` | `rental_model` → `rental_unit`; удалён `price_minor`; добавлены `battery_type`, `variants`, `allowed_durations`, `price_from`, `version` |
| `GET /public/lots`, `GET /public/lots/{slug}` | Отдают `price_from` вместо `price_minor`; точное количество АКБ не раскрывается |
| `GET /admin/lots` | Отдаёт варианты, тиры и `version`; `price_from` считается сервером |
| `POST /admin/lots` | Принимает `rental_unit`, `variants`, `allowed_durations`, `battery_type`; `price_minor`/`rental_model` удалены |
| `POST /rentals` | `CreateRentalRequest` требует `variant_id`; цена и `battery_count` берутся из варианта |
| `GET /public/lots/{slug}/availability` | Учитывает блоки (`kind: "block"` уже в `BusyInterval`) |
| `Rental`, `AdminRental` | Без изменений: `price_minor` — замороженная цена аренды |

## 3. Матрица прав CR-01

| Право | owner | admin | user | гость |
| ----- | :---: | :---: | :---: | :---: |
| Просмотр каталога, `quote`, доступности | ✅ | ✅ | ✅ | ✅ |
| `PATCH /admin/lots/{id}`, `POST /admin/lots` | ✅ | ❌ | ❌ | ❌ |
| Блоки, `GET /admin/schedule` | ✅ | ✅ | ❌ | ❌ |
| `GET/PATCH /admin/batteries*` | ✅ | ❌ | ❌ | ❌ |

Роли и права в целом — [`../docs/contract/README.md` §3.3](../docs/contract/README.md).

## 4. Порядок проверок в `POST /rentals`

1. `variant_id` принадлежит `lot_id` и `is_active` → иначе `422 validation_error`.
2. Длительность и `allowed_durations` → `422 rental_period_not_allowed`.
3. Занятость лота (аренды + блоки + `maintenance`) → `409 slot_taken`.
4. Ёмкость АКБ по типу → `409 battery_unavailable`.
5. Запись аренды с ценой из D-20; `Idempotency-Key` обязателен (D-08).

Порядок фиксирован: клиент получает один однозначный код, а не набор ошибок.
