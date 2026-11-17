# CR-01 · Контракт (CT-10, CT-11, CT-12)

> Навигация: [CR-01](README.md) · [Решения](decisions.md) · [Мок](mock.md) · [Фронтенд](frontend.md) · [Backend](backend.md) · [Приёмка](qa.md)

Все три задачи делаются **одним PR с меткой `contract`** (S0), чтобы мок и фронтенд не переделывались дважды:
`CT-10` задаёт форму данных, `CT-11` добавляет сроки/блоки, `CT-12` — остатки АКБ. Срезы S1–S3 — это поставка
мока и UI, а не повторные правки контракта.

Файлы: `contract/openapi.json`, `contract/pricing.md` (создаётся), `contract/decisions.md` (дополняется D-19…D-26),
`contract/endpoints.md` (дополняется операциями).

## 10.1. `CT-10` · Варианты, тарифы, quote

**Зависит:** CT-04 (кодогенерация), CT-06 (mock-контракт).
**Объём:** `Lot`, `CreateLotRequest`, `CreateRentalRequest`, новые `LotVariant`, `PriceTier`, `Quote`, `PriceFrom`;
новый эндпоинт `GET /api/v1/public/lots/{slug}/quote`; `PATCH /api/v1/admin/lots/{id}` (нужен, чтобы тарифы можно было
редактировать, а не только создать — `BE-LOT-01` это уже предполагает); `rental_model → rental_unit`.

```jsonc
Lot {
  "id": "uuid", "slug": "urban-one", "name": "Urban One",
  "description": "…", "category_id": "uuid", "photos": ["…"],
  "characteristics": { "power": 500 },
  "rental_unit": "day",                       // было: rental_model
  "battery_type": "48v",                      // null, если лот без АКБ
  "variants": [                               // minItems 1
    {
      "id": "uuid",
      "battery_count": 1,                     // 1 — один АКБ, 2 — два
      "is_active": true,
      "price_tiers": [
        { "min_units": 1,  "price_per_unit_minor": 130000 },
        { "min_units": 7,  "price_per_unit_minor": 40000 },
        { "min_units": 30, "price_per_unit_minor": 40000 }
      ]
    }
  ],
  "price_from": { "amount_minor": 40000, "per": "day", "at_units": 7, "battery_count": 1 },
  "status": "active", "is_bookable": true
}
```

```jsonc
LotVariant {
  "id": "uuid", "battery_count": 1, "is_active": true,
  "price_tiers": [{ "min_units": 1, "price_per_unit_minor": 130000 }]
}

PriceTier {
  "min_units": 1,
  "price_per_unit_minor": 130000
}

PriceFrom {
  "amount_minor": 40000,
  "per": "day",              // совпадает с rental_unit лота
  "at_units": 7,             // с какого срока действует цена
  "battery_count": 1         // в каком варианте
}
```

```jsonc
// CreateLotRequest
{
  "name": "Urban One", "category_id": "uuid", "description": "…",
  "rental_unit": "day", "battery_type": "48v",
  "variants": [{ "battery_count": 1, "price_tiers": [{ "min_units": 1, "price_per_unit_minor": 130000 }] }],
  "characteristics": { "power": 500 },
  "photos": ["…"], "status": "active"
}

// PATCH /api/v1/admin/lots/{id}
{ "version": 3, "variants": [ /* … */ ] }   // любой подмножество полей + version, 409 stale_version
```

```jsonc
// GET /api/v1/public/lots/{slug}/quote?start=…&end=…
{
  "lot_id": "uuid", "start": "…", "end": "…",
  "units": 10, "rental_unit": "day",
  "variants": [
    {
      "variant_id": "uuid", "battery_count": 1,
      "price_total_minor": 500000, "currency": "RUB",
      "tier_min_units": 7,
      "available": true, "unavailable_reason": null
    },
    {
      "variant_id": "uuid", "battery_count": 2,
      "price_total_minor": 500000, "currency": "RUB",
      "tier_min_units": 7,
      "available": true, "unavailable_reason": null
    }
  ]
}
```

```jsonc
// CreateRentalRequest — battery_count заменён на variant_id
{ "lot_id": "uuid", "variant_id": "uuid", "start_time": "…", "end_time": "…" }
```

**Правила (D-19…D-22 в [decisions.md](decisions.md)):**

- `rental_unit: "day" | "hour"` — `hourly → hour`, `daily/custom → day`. Поле `rental_model` удаляется.
- `variants[].battery_count` уникален в пределах лота; при `battery_count > 0` обязателен `battery_type`.
- `price_tiers` непустой, отсортирован, первая граница = `min(allowed_durations)` (проверяется в `CT-11`).
- `price_from` считает сервер; фронтенд не пересчитывает.
- Валюта — тенантская; в варианте не дублируется.

**AC:**

- [x] `pnpm gen:api` обновляет `frontend/app/shared/api/schema.d.ts` без ручных правок.
- [x] В контракте нет `price_minor` на `Lot` (цена периода — только `price_total_minor` в `Quote`) и нет `rental_model` ни в одном DTO.
- [x] `contract/pricing.md` содержит алгоритм D-20 и **20+** голден-векторов, включая границы тиров и round-up (45 векторов).
- [x] `PATCH /admin/lots/{id}` объявляет `409 stale_version` и `version` в ответе.
- [x] `quote` объявлен как `no-store` (цена зависит от интервала).

## 10.2. `CT-11` · Сроки, блоки, расписание

**Зависит:** CT-10.
**Объём:** `allowed_durations`, `POST/DELETE /api/v1/admin/lots/{id}/blocks`, `GET /api/v1/admin/schedule`,
расширение `Quote.unavailable_reason` значением `rental_period_not_allowed`; `contract/endpoints.md`.

```jsonc
// Lot (дополнение)
{ "allowed_durations": [1, 3, 7, 30] }        // единицы rental_unit, возрастание

// POST /api/v1/admin/lots/{id}/blocks
{ "start_time": "2026-11-20T00:00:00+03:00", "end_time": "2026-11-23T00:00:00+03:00",
  "reason": "Техобслуживание" }                // [start, end), целые сутки в TZ тенанта

// Block
{ "id": "uuid", "lot_id": "uuid", "start_time": "…", "end_time": "…",
  "reason": "…", "created_by": "uuid", "created_at": "…" }

// GET /api/v1/admin/schedule?from=2026-11-01&to=2026-11-30&category_id=uuid
{
  "lots": [{ "id": "uuid", "name": "Urban One", "category_id": "uuid",
             "status": "active", "battery_type": "48v", "rental_unit": "day" }],
  "intervals": [
    { "id": "uuid", "lot_id": "uuid", "kind": "rental",
      "start_time": "…", "end_time": "…", "rental_id": "uuid",
      "status": "booked", "battery_count": 2, "user_name": "Иван Петров" },
    { "id": "uuid", "lot_id": "uuid", "kind": "block",
      "start_time": "…", "end_time": "…", "block_id": "uuid", "reason": "Техобслуживание" }
  ],
  "battery_stock": [{ "battery_type": "48v", "quantity": 12, "peak_committed": 7 }]
}
```

**AC:**

- [x] `allowed_durations` валидируется: отсортирован, без дублей, ≥ 1, не шире 365.
- [x] Блоки не пересекаются с `booked`/`active` арендой → `409 slot_taken`; причина 3–200 символов. _Проверено на моке: блок поверх `booked`-аренды → `409 slot_taken`._
- [x] `schedule` возвращает лоты **без** событий (иначе гант не нарисует пустые строки). _Проверено: `GET /admin/schedule` отдаёт 6 лотов, включая лот без интервалов._
- [x] `schedule` объявлен `no-store`, окно ≤ 90 дней → иначе `422`.
- [x] Часовой лот (`rental_unit: hour`) в `schedule` отдаётся как есть, без special-case.

## 10.3. `CT-12` · Остатки АКБ и ёмкость

**Зависит:** CT-10.
**Объём:** `battery_type` (уже в `CT-10`), `BatteryStock`, `GET/PATCH /api/v1/admin/batteries`,
значение `Quote.variants[].unavailable_reason = "battery_unavailable"`, коды `battery_unavailable`,
`stock_below_committed`; правило ёмкости D-23 в `pricing.md`.

```jsonc
// GET /api/v1/admin/batteries
[{ "battery_type": "48v", "name": "48V 720 Вт·ч", "quantity": 12, "peak_committed": 7 }]

// PATCH /api/v1/admin/batteries/{battery_type}
{ "quantity": 14 }        // 409 stock_below_committed, если quantity < peak_committed на горизонте броней
```

**AC:**

- [x] Ёмкость в контракте описана как сумма `battery_count` по интервалу, а не счётчик «выдано/свободно».
- [x] `stock_below_committed` объявлен с описанием горизонта (все активные и будущие брони).
- [x] `battery_type` — обязательное поле стока; тип без единого лота допустим (закупка впрок).
- [x] Каталог и quote не раскрывают точное количество, только `available` (антиконкурентная утечка не нужна).

## 10.4. Коды ошибок CR-01

| Код | HTTP | Где | Текст для UI |
| --- | ---- | --- | ----------- |
| `rental_period_not_allowed` | 422 | `POST /rentals`, `quote` | «Минимальный срок аренды — 7 дней» |
| `battery_unavailable` | 409 | `POST /rentals`, `quote` (`unavailable_reason`) | «Свободных аккумуляторов на эти даты нет» |
| `stock_below_committed` | 409 | `PATCH /admin/batteries/{type}` | «Нельзя уменьшить: 12 шт. уже забронированы» |
| `slot_taken` | 409 | `POST /admin/lots/{id}/blocks`, `POST /rentals` | «В эти дни лот занят» (переиспользуется) |
| `stale_version` | 409 | `PATCH /admin/lots/{id}` | «Лот изменён другим администратором» (переиспользуется) |

## 10.5. Миграция

| Было | Стало | Правило |
| ---- | ----- | ------- |
| `rental_model: hourly` | `rental_unit: hour` | 1:1 |
| `rental_model: daily/custom` | `rental_unit: day` | `custom` больше не отдельный режим |
| `price_minor: N` | `variants: [{ battery_count: 1, price_tiers: [{ min_units: 1, price_per_unit_minor: N }] }]` | 1:1, цена не меняется для суточных лотов |
| `allowed_durations` отсутствует | `[1]` | лот продолжает продаваться посуточно, пока админ не поменяет |
| `battery_type` отсутствует | `null` | для лотов категории «Аккумуляторы» — по коду характеристики, иначе вручную |

Миграция лотов-аккумуляторов (`Spare 48V` и т. п.) в пул стока — **вне CR**: они остаются лотами, но получают
`battery_type`, чтобы не ломать каталог.
