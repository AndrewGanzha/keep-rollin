# Расчёт цены и ёмкости АКБ (D-19…D-25)

> Контракт: [README](README.md) · [openapi.json](openapi.json) · Решения: [decisions.md](decisions.md) · CR-01: [README](../docs/changes/cr-01/README.md)

Единственный источник правды для цены аренды и проверки ёмкости аккумуляторов. Мок (`MOCK-01`, `MOCK-03`)
и backend (`BE-BOOK-05`, `BE-AVA-01`) обязаны воспроизводить алгоритмы ниже на всех голден-векторах из §4–§6.
Клиент цену не считает: он показывает `Lot.price_from` и `Quote.variants[].price_total_minor`.

## 1. Входные данные

| Поле | Где | Смысл |
| ---- | --- | ----- |
| `lot.rental_unit` | `Lot` | `day` или `hour` — единица срока (D-19) |
| `lot.allowed_durations` | `Lot` | Разрешённые пресеты срока в единицах `rental_unit`, по возрастанию, без дублей (D-25) |
| `lot.battery_type` | `Lot` | Тип АКБ из пула `battery_stock`; `null` — лот без АКБ |
| `variant.battery_count` | `LotVariant` | Сколько АКБ занимает вариант; `0` — без АКБ |
| `variant.price_tiers` | `LotVariant` | Тиры `{min_units, price_per_unit_minor}`, по возрастанию `min_units` (D-19) |
| `start`, `end` | `Quote`, `POST /rentals` | Полуинтервал `[start, end)`, ISO-8601 (D-05) |

Деньги — целые минорные единицы (`price_per_unit_minor`, `price_total_minor`), валюта — тенантская (D-06).
Дробных промежуточных значений нет: все вычисления в целых числах.

Длительность единицы: `day = 24 h`, `hour = 1 h`. Календарные месяцы не используются: месяц = 30 единиц (D-21).

Согласно D-19, прежние `daily` и `custom` соответствуют `rental_unit: day`, а `hourly` — `rental_unit: hour`. Фиксированная цена за произвольный период отложена за рамки MVP. Сумму для суточного лота рассчитывают по тирам и правилам D-20.

## 2. Алгоритм D-20

```
quote(variant, allowed_durations, rental_unit, start, end):
  1. if end <= start: 422 validation_error
  2. units = ceil((end - start) / unit_length)
  3. if units < min(allowed_durations): 422 rental_period_not_allowed
  4. tier = последний тир, у которого min_units <= units
  5. total = units * tier.price_per_unit_minor
  6. for t in tiers, где t.min_units > units:
        total = min(total, t.min_units * t.price_per_unit_minor)   # round-up
  7. return { total, tier_min_units: min_units тира, который дал итог }
```

Правила:

- `units` округляется **вверх**: 23 часа на суточном лоте = 1 сутки; 1 сутки 1 час = 2 суток.
- Шаг 6 — потолок цены по более длинному пакету: 29 суток не могут стоить дороже 30-суточного пакета.
  Срок аренды не меняется, меняется только цена; UI подписывает «выгоднее взять на 30 суток».
- Round-up может сработать несколько раз — берётся минимум по всем более длинным тирам, а не только по следующему.
- `tier_min_units` в ответе — `min_units` тира, чья цена победила после шага 6 (для варианта A/3 суток это `7`,
  а не `1`).
- Один и тот же расчёт используется в `GET /public/lots/{slug}/quote`, в `POST /rentals` (цена замораживается
  в `rental.price_minor`) и в демо-генерации мока.

### 2.1. `price_from` (D-22)

`price_from` — минимум `price_per_unit_minor` по всем **активным** вариантам и их тирам.

- `amount_minor` — этот минимум, `per = lot.rental_unit`.
- `at_units` — `min_units` тира, где встретился минимум.
- `battery_count` — вариант, где встретился минимум.
- При равенстве `amount_minor` побеждает меньший `at_units`, затем меньший `battery_count`.
- Если активных вариантов нет — `price_from: null`; витрина показывает заглушку, а не выдуманную цену.

## 3. Инварианты, которые обязаны проверять админ-форма и сервер

| # | Инвариант | Код при нарушении |
| - | --------- | ----------------- |
| P-1 | `price_tiers` непустой, `min_units` уникальны и возрастают | `422 validation_error`, путь `variants[i].price_tiers[j].min_units` |
| P-2 | `price_tiers[0].min_units == min(allowed_durations)` | `422 validation_error` |
| P-3 | `price_per_unit_minor` не возрастает при росте `min_units` | `422 validation_error` |
| P-4 | `allowed_durations` непустой, уникальный, по возрастанию, `1 ≤ d ≤ 365` | `422 validation_error` |
| P-5 | `battery_count` уникален в пределах лота | `422 validation_error` |
| P-6 | `battery_count > 0` требует `lot.battery_type` | `422 validation_error` |
| P-7 | `units < min(allowed_durations)` | `422 rental_period_not_allowed` |
| P-8 | `end <= start` | `422 validation_error` |

P-3 — защита от «длинная аренда дороже короткой»; round-up из шага 6 не маскирует нарушение, потому что
инвариант проверяется на самих тирах.

## 4. Голден-векторы: суточный лот

Канонический лот `urban-one`:

```jsonc
"rental_unit": "day",
"allowed_durations": [1, 3, 7, 30],
"variants": [
  { "battery_count": 1, "price_tiers": [
      { "min_units": 1,  "price_per_unit_minor": 130000 },
      { "min_units": 7,  "price_per_unit_minor": 40000 },
      { "min_units": 30, "price_per_unit_minor": 40000 } ] },
  { "battery_count": 2, "price_tiers": [
      { "min_units": 1,  "price_per_unit_minor": 150000 },
      { "min_units": 7,  "price_per_unit_minor": 50000 },
      { "min_units": 30, "price_per_unit_minor": 40000 } ] }
]
```

Для этого лота `price_from = { amount_minor: 40000, per: "day", at_units: 7, battery_count: 1 }`
(400 ₽/сут встречается у варианта 1 АКБ с 7 суток и у варианта 2 АКБ с 30 суток; побеждает меньший `at_units`).

| № | Суток | Вариант | Сработавший тир | Расчёт | Итог, ₽ |
| -: | ----: | ------- | --------------: | ------ | ------: |
| 1 | 1 | 1 АКБ | 1 | 1 × 1 300 | 1 300 |
| 2 | 1 | 2 АКБ | 1 | 1 × 1 500 | 1 500 |
| 3 | 2 | 1 АКБ | 1 | 2 × 1 300 = 2 600; min(2 600, 7 × 400) | 2 600 |
| 4 | 2 | 2 АКБ | 1 | 2 × 1 500 = 3 000; min(3 000, 7 × 500) | 3 000 |
| 5 | 3 | 1 АКБ | 7 | 3 × 1 300 = 3 900; min(3 900, 2 800) | 2 800 |
| 6 | 3 | 2 АКБ | 7 | 3 × 1 500 = 4 500; min(4 500, 3 500) | 3 500 |
| 7 | 4 | 1 АКБ | 7 | 4 × 1 300 = 5 200; min(5 200, 2 800) | 2 800 |
| 8 | 4 | 2 АКБ | 7 | 4 × 1 500 = 6 000; min(6 000, 3 500) | 3 500 |
| 9 | 5 | 1 АКБ | 7 | 5 × 1 300 = 6 500; min(6 500, 2 800) | 2 800 |
| 10 | 5 | 2 АКБ | 7 | 5 × 1 500 = 7 500; min(7 500, 3 500) | 3 500 |
| 11 | 6 | 1 АКБ | 7 | 6 × 1 300 = 7 800; min(7 800, 2 800) | 2 800 |
| 12 | 6 | 2 АКБ | 7 | 6 × 1 500 = 9 000; min(9 000, 3 500) | 3 500 |
| 13 | 7 | 1 АКБ | 7 | 7 × 400 | 2 800 |
| 14 | 7 | 2 АКБ | 7 | 7 × 500 | 3 500 |
| 15 | 8 | 1 АКБ | 7 | 8 × 400; min(3 200, 30 × 400) | 3 200 |
| 16 | 8 | 2 АКБ | 7 | 8 × 500; min(4 000, 12 000) | 4 000 |
| 17 | 10 | 1 АКБ | 7 | 10 × 400 | 4 000 |
| 18 | 10 | 2 АКБ | 7 | 10 × 500 | 5 000 |
| 19 | 29 | 1 АКБ | 7 | 29 × 400 = 11 600; min(11 600, 12 000) = 11 600 — месяц не дешевле, round-up не срабатывает | 11 600 |
| 20 | 29 | 2 АКБ | 7 | 29 × 500 = 14 500; min(14 500, 12 000) — round-up до месяца | 12 000 |
| 21 | 30 | 1 АКБ | 30 | 30 × 400 | 12 000 |
| 22 | 30 | 2 АКБ | 30 | 30 × 400 | 12 000 |
| 23 | 31 | 1 АКБ | 30 | 31 × 400 | 12 400 |
| 24 | 31 | 2 АКБ | 30 | 31 × 400 | 12 400 |
| 25 | 60 | 1 АКБ | 30 | 60 × 400 | 24 000 |
| 26 | 60 | 2 АКБ | 30 | 60 × 400 | 24 000 |

Проверки из таблицы: 3 ≤ 7 суток по цене, 29 ≤ 30 суток, 30 ≤ 31, цена не убывает с ростом срока.
Вектор 19 специально фиксирует, что round-up не всегда срабатывает: у варианта 1 АКБ 29 суток уже дешевле месяца.

## 5. Голден-векторы: часовой лот

Лот `scooter-hour`:

```jsonc
"rental_unit": "hour",
"allowed_durations": [1, 3, 24],
"variants": [
  { "battery_count": 0, "price_tiers": [
      { "min_units": 1,  "price_per_unit_minor": 50000 },
      { "min_units": 3,  "price_per_unit_minor": 40000 },
      { "min_units": 24, "price_per_unit_minor": 30000 } ] }
]
```

`price_from = { amount_minor: 30000, per: "hour", at_units: 24, battery_count: 0 }`.

| № | Часов | Тир | Расчёт | Итог, ₽ |
| -: | ----: | --: | ------ | ------: |
| 27 | 1 | 1 | 1 × 500 | 500 |
| 28 | 2 | 1 | 2 × 500 = 1 000; min(1 000, 3 × 400) | 1 000 |
| 29 | 3 | 3 | 3 × 400 | 1 200 |
| 30 | 4 | 3 | 4 × 400 = 1 600; min(1 600, 24 × 300) | 1 600 |
| 31 | 23 | 3 | 23 × 400 = 9 200; min(9 200, 7 200) — round-up до суток | 7 200 |
| 32 | 24 | 24 | 24 × 300 | 7 200 |
| 33 | 25 | 24 | 25 × 300 | 7 500 |

## 6. Голден-векторы: границы и ошибки

| № | Вход | Ожидание |
| -: | ---- | -------- |
| 34 | суточный лот, `start = 10:00Z`, `end = 09:00Z` следующих суток | `units = 1` (23 ч округлены вверх), цена вектора 1 |
| 35 | суточный лот, `start = 00:00Z`, `end = 01:00Z` | `units = 1` |
| 36 | суточный лот, `start = 00:00Z`, `end = 24:00Z` | `units = 1` (ровно одни сутки) |
| 37 | `end == start` | `422 validation_error`, `units` не считается |
| 38 | `end < start` | `422 validation_error` |
| 39 | `allowed_durations = [7, 30]`, `units = 6` | `422 rental_period_not_allowed` |
| 40 | `allowed_durations = [30]`, `units = 29` | `422 rental_period_not_allowed` |
| 41 | `allowed_durations = [1, 3, 7, 30]`, `units = 0` | `422 validation_error` (не `rental_period_not_allowed`) |
| 42 | тиры `1 → 1 300`, `7 → 1 500` (цена растёт) | `422 validation_error`, путь `variants[0].price_tiers[1].price_per_unit_minor` (P-3) |
| 43 | `allowed_durations = [7, 3]` | `422 validation_error` (порядок, P-4) |
| 44 | `allowed_durations = [1, 1]` | `422 validation_error` (дубль, P-4) |
| 45 | два варианта с `battery_count = 2` | `422 validation_error` (P-5) |

Итого 45 векторов; `frontend/tests/pricing.test.ts` и backend `test_pricing_vectors.py` используют §4–§6 дословно.
Если меняется алгоритм — сначала меняется этот файл, затем тесты, затем реализация.

## 7. Ёмкость аккумуляторов (D-23)

Любая аренда с `battery_count = k` занимает `k` АКБ типа `lot.battery_type` на весь интервал `[start, end)`.

```
peak(battery_type, interval):
  events = []
  for rental in rentals where status in {booked, active} and battery_type matches:
      events += [(rental.start, +rental.battery_count), (rental.end, -rental.battery_count)]
  sort events by time, при равенстве времени сначала -k, затем +k
  running = 0; peak = 0
  for (time, delta) in events:
      running += delta; peak = max(peak, running)
  return peak
```

Правила:

1. Новая бронь отклоняется, если `peak` после её добавления превышает `battery_stock.quantity` → `409 battery_unavailable`.
2. Проверка ёмкости выполняется **после** проверки слота лота, чтобы код ошибки был однозначным, и в одной
   транзакции с созданием аренды; строка `battery_stock` блокируется (`SELECT … FOR UPDATE`).
3. `quote.variants[].available` считается тем же `peak`; причина `battery_unavailable`. Точное количество
   в каталог и quote не попадает.
4. `PATCH /admin/batteries/{battery_type}` с `quantity < peak_committed` → `409 stock_below_committed`;
   `peak_committed` — пик по всем активным и будущим арендам на всём горизонте, не только в окне запроса.
5. Блоки (`lot_blocks`), статусы `maintenance`/`archived` и отменённые/завершённые аренды ёмкость не расходуют.
   Отмена и закрытие освобождают АКБ при следующем запросе.
6. Пик считается по интервалу, а не по сумме выдач: непересекающиеся аренды не складываются.

Пример: сток 48V = 12; аренда A «2 АКБ» пн–вс, аренда B «1 АКБ» ср–сб, новая бронь C «2 АКБ» чт–пт.
Пик в четверг: 2 + 1 + 2 = 5 ≤ 12 → бронь разрешена. Заблокированные дни и `maintenance` в пик не входят.

## 8. Соответствие полям контракта

| Величина | Поле в `openapi.json` |
| -------- | --------------------- |
| Тиры варианта | `LotVariant.price_tiers[]` (`PriceTier`) |
| Цена «от» | `Lot.price_from` (`PriceFrom`) |
| Цена за интервал | `Quote.variants[].price_total_minor`, `tier_min_units` |
| Доступность варианта | `Quote.variants[].available`, `unavailable_reason` |
| Занятая ёмкость | `BatteryStock.peak_committed` |
| Замороженная цена аренды | `Rental.price_minor` / `AdminRental.price_minor` (не меняется при правке тарифов) |
