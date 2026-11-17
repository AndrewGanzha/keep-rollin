# CR-01 · Мок (MOCK-01…MOCK-03)

> Навигация: [CR-01](README.md) · [Решения](decisions.md) · [Контракт](contract.md) · [Фронтенд](frontend.md) · [Backend](backend.md) · [Приёмка](qa.md)

Файл: `frontend/mock-server.config.ts` (stateful, запуск `pnpm mock` / `pnpm dev:full`).
Типы — только из `frontend/app/shared/api/schema.d.ts`, после `pnpm gen:api`. Ручных DTO в моке не появляется.

## MOCK-01 · Тарифы, варианты, quote и запись лота

**Зависит:** CT-10.
**Срез:** S1.

**Объём:**

1. `makeLot(...)` и `lots[]` перевести на `rental_unit`, `variants`, `price_tiers`, `price_from`, `allowed_durations`,
   `battery_type`. Разовые цены лотов сохранить как тир `min_units: 1`, чтобы сумма не «прыгнула» на демо.
2. **Двум лотам сразу дать второй вариант** `battery_count: 2` (например `Urban One` и `Cargo Max`) с **отличными
   тирами** (2 АКБ дороже на коротком сроке, как в цифрах заказчика), чтобы S1 демонстрировал выбор 1/2 АКБ.
   Ограничение остатком не подключается — это S3 (`MOCK-03`), у остальных лотов остаётся один вариант.
3. `priceFor` (сейчас `mock-server.config.ts:478`) заменить модулем расчёта по D-20: выбор тира + round-up.
   Функция используется и в `POST /rentals`, и в `quote`, и в генерации `rentals[]` для демо.
4. `price_from` считать при выдаче лота (`GET /public/lots`, `GET /public/lots/{slug}`, `GET /admin/lots`), а не
   хардкодить в фикстурах.
5. Новый `GET /api/v1/public/lots/:slug/quote` → цены и `available` по каждому варианту.
6. **Переписать write-путь админ-лотов.** Сейчас `POST /api/v1/admin/lots` (`:1129`) валидирует `price_minor` и
   `rental_model`; после CT-10 этих полей нет. Нужно: приём `variants`/`price_tiers`/`allowed_durations`/`rental_unit`/
   `battery_type`, те же инварианты, что в `decisions.md`, и `price_from` в ответе. Добавить
   `PATCH /api/v1/admin/lots/:id` с `version` → `409 stale_version`, иначе `FE-LOT-05` нечем сохранить правку тарифов.

**AC:**

- [x] `pnpm gen:api` → мок компилируется без `as any` на новых DTO.
- [x] 29 суток не дороже 30; 3 суток не дороже недели — совпадает с таблицей векторов `decisions.md` (проверено `tests/pricing.test.ts`).
- [x] В каталоге есть минимум один лот с двумя вариантами; `price_from` у него — минимум по вариантам.
- [x] `POST /admin/lots` с сеткой, где цена растёт с длиной срока, → `422 validation_error` с путём поля.
- [x] `PATCH /admin/lots/:id` со старым `version` → `409 stale_version`; с новым — лот виден обновлённым в `GET /admin/lots`.
- [x] `quote` не пишет в состояние: повторный вызов возвращает то же.

## MOCK-02 · Блоки и расписание

**Зависит:** CT-11, MOCK-01.
**Срез:** S2.

**Объём:**

1. `blocks` из read-only карты (`mock-server.config.ts`, `const blocks`) превратить в writable-состояние с `id`,
   `reason`, `created_by`.
2. `POST /api/v1/admin/lots/:id/blocks` — выравнивание границ по суткам, пересечение с `booked`/`active` → `409 slot_taken`,
   причина 3–200 → иначе `422`.
3. `DELETE /api/v1/admin/lots/:id/blocks/:block_id` → `204`, состояние обновляется, публичная доступность видит изменение.
4. `GET /api/v1/admin/schedule` — лоты (включая свободные), интервалы аренд и блоков, `battery_stock` с живым
   `peak_committed`.
5. Публичная `GET /public/lots/:slug/availability` должна учитывать блоки (`kind: "block"` уже в контракте).

**AC:**

- [x] Созданный блок виден в `schedule` и в `availability` без перезапуска мока.
- [x] Блок поверх аренды → `409 slot_taken` с понятным `detail`.
- [x] `schedule` отдаёт лоты без событий (иначе гант теряет строки).
- [x] Удаление блока освобождает дни для новой брони (проверяется `POST /rentals`).
- [x] Границы блоков не зависят от TZ машины разработчика (использовать TZ тенанта, как `shared/lib/calendar.ts`).

## MOCK-03 · Остатки АКБ и ёмкость

**Зависит:** CT-12, MOCK-01, MOCK-02.
**Срез:** S3.

**Объём:**

1. `battery_stock: [{ battery_type, name, quantity }]` — 48V/36V, количества как в демо-парке.
2. `GET /api/v1/admin/batteries`, `PATCH /api/v1/admin/batteries/:battery_type` → `409 stock_below_committed`,
   если новое количество меньше пика по активным и будущим броням.
3. `POST /rentals` для варианта с `battery_count > 1`: посчитать пик по типу на интервал (события `start +k` / `end −k`
   по `booked`/`active`), при превышении → `409 battery_unavailable`; проверить **после** проверки слота лота, чтобы
   код ошибки был однозначным.
4. `quote.variants[].available` для второго варианта — из того же расчёта пика.
5. Отмена (`POST /me/rentals/:id/cancel`) и закрытие аренды освобождают АКБ — пересчитать при следующем запросе.
6. Демо-кейс в seed: 48V = 3 при одной забронированной паре `cargo-max` (пик 2). Вторая пара на те же дни
   недоступна (2 + 2 > 3), а одиночная АКБ влезает (2 + 1 = 3) — ровно просьба «с двумя нет, с одним есть».
7. Расчёт пика — чистый модуль `frontend/mock/capacity.ts` (`peakUsage`), покрыт `frontend/tests/capacity.test.ts`.

**AC:**

- [x] Сток 12, десять аренд по 1 АКБ и одна по 2 (пик 12); новая аренда «с двумя» → `409 battery_unavailable`. _Сценарий закреплён вектором в `tests/capacity.test.ts`; в seed сток 3, чтобы отказ воспроизводился на демо-парке._
- [x] Отмена аренды возвращает вариант в `available: true` в `quote`.
- [x] Уменьшение стока ниже пика → `409 stock_below_committed`.
- [x] Пик считается по интервалу, а не «сколько раз всего выдали» (аренды не пересекаются → ёмкость не тратится).
- [x] Блоки и `maintenance` остаток не расходуют.

## Общие требования к моку

- Состояние живёт в памяти процесса; после перезапуска — демо-seed, как сейчас.
- Ни одна ветка не возвращает 500 на валидном по контракту запросе; ошибки — только объявленные коды.
- Расчётные функции (цена, пик ёмкости) — чистые и экспортируемые, чтобы покрыть их в `frontend/tests`.
