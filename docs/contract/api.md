# 4. Каталог эндпоинтов (контракт)

> Часть плана MVP. Навигация: [README](../../README.md) · [Контракт](README.md) · [API](api.md) · [Модель данных](data-model.md) · [Задачи](../tasks/README.md) · [Поставка](../delivery.md)

Роли: `гость` — без токена; `user`, `admin`, `owner` — см. §3.3. Все пути с префиксом `/api/v1`.

`*` MFA setup/confirm доступны без access-токена: короткоживущий `mfa_token` выдаётся после проверки пароля и подтверждает только право завершить enrollment для этого пользователя.

### 4.1. Публичные и сессия

| Метод и путь                              | Роли  | Назначение / заметки |
| ----------------------------------------- | ----- | -------------------- |
| `GET /public/tenant`                      | гость | Брендинг, tz, currency, контакты, policies, `vapid_public_key` |
| `GET /public/categories`                  | гость | Активные категории и определения характеристик. Счётчики лотов запланированы |
| `GET /public/lots`                        | гость | Поиск, типизированные фильтры, период, сортировка; только активные лоты |
| `GET /public/lots/{slug}`                 | гость | Карточка; 404 для `archived`/`maintenance`/`overdue` |
| `GET /public/lots/{slug}/availability`    | гость | §3.7 |
| `GET /public/availability`                | гость | Сводка по времени и опциональной категории (§3.7, UC-2.2) |
| `GET /public/offers/current`              | гость | Активная версия оферты (текст + версия) |
| `GET /health`, `GET /readyz` | infra | Liveness / readiness (Prometheus `/metrics` — follow-up BE-WRK-01) |

Параметры каталога `GET /public/lots`

- `category_id`, `q`, `limit` (20 по умолчанию, до 100) и `offset` сохраняют существующее поведение. `total` считает все совпадения до пагинации.
- `char_<code>` проверяет равенство значения лота. Числа сравниваются численно, текст и значения выбора — с учётом регистра. Учитываются активные определения выбранной категории. Без `category_id` значение проверяется по активным определениям тенанта, а совпадение засчитывается для подходящей категории. Неизвестный параметр запроса, повтор фильтра характеристики или значение, не подходящее ни к одному определению, возвращает `422 validation_error`.
- `available_from` и `available_to` задаются вместе. Применяются ограничения §3.7. В выборку попадает лот с активным вариантом без пересечения с активным интервалом занятости. Цена и минимальная длительность проверяются при запросе котировки.
- `sort` принимает `newest` (по умолчанию), `name_asc`, `price_asc` и `price_desc`. Цена сравнивается по `price_from.amount_minor` в минорных единицах, пустая цена всегда в конце. Порядок при равенстве стабилен.
- Категории, список и карточка лота поддерживают `ETag` и `If-None-Match`. Совпадающий валидатор даёт `304` без тела. Заголовки кеша присутствуют в обоих успешных ответах.

### 4.2. Аутентификация и профиль

| Метод и путь                     | Роли  | Назначение / заметки |
| -------------------------------- | ----- | -------------------- |
| `POST /auth/register`            | гость | email+phone+password → 201 + токены |
| `POST /auth/login`               | гость | → токены или `mfa_required`/`mfa_setup_required` |
| `POST /auth/mfa/verify`          | гость | `mfa_token` + TOTP/recovery-код → токены |
| `POST /auth/mfa/setup`           | гость* | `mfa_token` (purpose `enroll`) → секрет + otpauth-URI |
| `POST /auth/mfa/confirm`         | гость* | `mfa_token` + код → токены + 10 recovery-кодов |
| `POST /auth/refresh`             | cookie | Ротация refresh |
| `POST /auth/logout`              | все   | Отзыв сессии, очистка cookie |
| `POST /auth/password/forgot`     | гость | Всегда 202 (без enumeration) |
| `POST /auth/password/reset`      | гость | Токен + новый пароль; 204 |
| `GET /auth/session`              | все   | user, tenant, role, `permissions[]`, `verification_status`, `offer_accepted`, `mfa_enabled` и `prefs_summary.push_enabled` |
| `GET /me/push-subscriptions`     | user+ | Активные подписки владельца. Ответ содержит ID и SHA-256 endpoint без адреса и ключей |
| `POST /me/push-subscriptions`    | user+ | Upsert по `endpoint` в формате браузера `{endpoint, expirationTime, keys:{p256dh,auth}}`. 409 при конфликте владельца или лимите 10 активных подписок |
| `DELETE /me/push-subscriptions/{subscription_id}` | user+ | Отписка владельца, 204 при повторном запросе |
| `GET /me/notification-preferences` | user+ | §3.10 |
| `PUT /me/notification-preferences` | user+ | Критичные события отключить нельзя |

### 4.3. Каталог (owner)

| Метод и путь                                      | Назначение / заметки |
| ------------------------------------------------- | -------------------- |
| `GET /admin/categories`                           | `include_archived`, пагинация |
| `POST /admin/categories`                          | name, slug, description |
| `PATCH /admin/categories/{id}`                    | Требует `version`; архив = `is_archived=true` |
| `PUT /admin/categories/{id}/characteristics`      | Bulk: создать/изменить/архивировать; требует `version` |
| `GET /admin/lots`                                 | `category_id`, `status`, `q`, пагинация |
| `POST /admin/lots`                                | Характеристики, `file_ids`, модель, цена |
| `GET /admin/lots/{id}`                            | Деталь + `version` |
| `PATCH /admin/lots/{id}`                          | Требует `version` |
| `POST /admin/lots/{id}/status`                    | Владелец меняет статус и получает обновлённый лот. Правила переходов приведены ниже |
| `POST /admin/lots/bulk`                           | `{template, count}`, 1–50, Idempotency-Key, 201 `{items}` |
| `POST /admin/lots/{id}/blocks`                    | Ручная блокировка (UC-2.4) |
| `DELETE /admin/lots/{id}/blocks/{block_id}`       | Снять блокировку |
| `POST /files`                                     | Multipart с `file` и `purpose`. Возвращает 201 с `file_id` и подписанным `url` |

Создание и правка лота принимают `file_ids` или массив публичных HTTP(S)-ссылок `photos`, который использует существующая админская форма. Ссылки с подписью S3 или Google Cloud Storage отклоняются. Переданный пустой массив очищает фото, а при пропуске поля в PATCH фотографии остаются. Чужой, отсутствующий или неподходящий `file_id` даёт 404. Стабильные публичные URL возвращаются в `photos` в порядке привязки.

При создании статус по умолчанию `active`. Можно явно создать `archived` лот. PATCH принимает текущий статус для совместимости с формой. При изменении цены или активности варианта его UUID сохраняется, если неизменён `battery_count`.

Владелец меняет статус через `POST /admin/lots/{id}/status` с телом `{"status":"active"}`, `{"status":"archived"}` или `{"status":"maintenance"}`. Повтор текущего статуса возвращает лот с той же версией. Реальный переход повышает версию и сохраняет `lot.status_changed` в той же транзакции.

Активная запись брони или аренды блокирует архивацию и перевод в обслуживание с `409 lot_has_active_rental`, пока занятость не освобождена. Вход в `maintenance` создаёт бессрочный интервал занятости, а выход закрывает его и сохраняет историю. Пересечение с существующим календарным блоком даёт `409 slot_taken`. Напрямую присвоить `overdue` нельзя, а выход из него выполняется при закрытии аренды.

`POST /files` требует сессию и обычные заголовки CSRF. `lot_photo` доступен владельцу. Остальные назначения хранятся в приватном бакете. Подписанная ссылка из ответа действительна пять минут по умолчанию, ответ имеет `Cache-Control: no-store`. Несовпадение MIME и содержимого даёт 422 `upload_invalid`, превышение лимита — 413 `payload_too_large`.

`POST /admin/lots/bulk` принимает шаблон обычного лота. Имена внутри пакета получают суффикс ` №N`, слаги — `-N`. База слага берётся из шаблона или генерируется из имени. Порядок `items` соответствует нумерации. Конфликт с существующим слагом возвращает `409 slug_taken` и откатывает весь пакет.

### 4.4. Календарь и доступность (staff)

| Метод и путь                  | Роли        | Назначение / заметки |
| ----------------------------- | ----------- | -------------------- |
| `GET /admin/calendar`         | admin, owner | `from`, `to`, `category_id`, `lot_id`, `status`; ≤ 200 лотов |
| `GET /admin/lots/{id}/calendar` | admin, owner | Детальный календарь лота с rental/block |

### 4.5. Верификация и оферта

| Метод и путь                                    | Роли        | Назначение / заметки |
| ----------------------------------------------- | ----------- | -------------------- |
| `POST /me/verification-requests`                | user+       | Паспортные данные + 3 документа; Idempotency-Key |
| `GET /me/verification-requests`                 | user+       | История заявок |
| `GET /me/verification-requests/{id}`            | user+       | Статус, комментарий, даты и подписанные URL документов своей заявки |
| `GET /admin/verification-requests`              | admin, owner| Очередь, фильтр `status`, пагинация |
| `GET /admin/verification-requests/{id}`         | admin, owner| Деталь с паспортными полями и подписанными URL документов |
| `POST /admin/verification-requests/{id}/decision` | admin, owner | `{decision, comment, version}`; 409 `already_processed` |
| `GET /admin/audit-log`                          | owner       | Фильтры по актору/сущности/дате, keyset-пагинация |
| `GET /admin/offers`                             | owner       | Версии оферты |
| `POST /admin/offers`                            | owner       | Новая версия (draft) |
| `PATCH /admin/offers/{id}`                      | owner       | Правка draft |
| `POST /admin/offers/{id}/publish`               | owner       | Активирует, прежняя → `archived` |
| `POST /me/offer-acceptances`                    | user+       | `{offer_version_id}`; идемпотентно |
| `GET /me/offer-acceptances`                     | user+       | История принятий |

При подаче `passport` содержит `full_name`, `birth_date` (YYYY-MM-DD), `passport_number` и `issued_by`. Объект `documents` содержит три идентификатора под ключами `verification_passport`, `verification_registration` и `verification_selfie`. Заявитель получает эти идентификаторы через `POST /files`. После отказа можно подать новую заявку. При наличии действующей заявки на проверке или одобрении сервер возвращает `409 conflict`.

Списки, ответ о подаче и ответ о решении содержат сводку. Свежие ссылки на приватные документы выдаются в деталях заявки, стандартный срок — пять минут. В ответах верификации применяется `Cache-Control: no-store`. Для отказа нужен непустой комментарий. Изменение статуса, запись аудита и постановка события в outbox выполняются в одной транзакции.

### 4.6. Брони и аренды

| Метод и путь                        | Роли        | Назначение / заметки |
| ----------------------------------- | ----------- | -------------------- |
| `POST /rentals`                     | user+       | Бронь; Idempotency-Key; сервер считает цену; 409 `slot_taken` |
| `GET /me/rentals`                   | user+       | `status`, пагинация |
| `GET /me/rentals/{id}`              | user+       | `remaining_seconds`, `cancellation_deadline`, лот, тикеты |
| `POST /me/rentals/{id}/cancel`      | user+       | По policy; 409 `cancellation_not_allowed` |
| `GET /admin/rentals`                | admin, owner| `status`, `user_id`, `lot_id`, `from`, `to` |
| `GET /admin/rentals/{id}`           | admin, owner| Деталь + пользователь |
| `POST /admin/rentals/{id}/cancel`   | admin, owner| Причина обязательна |
| `POST /admin/rentals/{id}/close`    | admin, owner| Возврат лота; `{comment, lot_status}`; UC-10.5 |


`POST /rentals` принимает `lot_id`, `variant_id`, `start_time` и `end_time`. Сервер проверяет верификацию, принятие актуальной оферты, статус лота и политику тенанта. Горизонт проверяется по началу интервала. Стоимость, валюта, тип и число АКБ сохраняются на момент бронирования. При одновременном конфликте сначала возвращается `409 slot_taken`. Если лот свободен, но аккумуляторов не хватает, ответ — `409 battery_unavailable`.

Дедлайн отмены равен началу аренды минус `cancellation_free_hours` на момент бронирования. Пользователь может отменить свою бронь в статусе `booked` до дедлайна включительно. Сотрудник может отменить `booked` или `active` с причиной. Повторная отмена возвращает сохранённое состояние. При закрытии в `maintenance` пересечение нового бессрочного интервала с будущей бронью или блоком возвращает `409 slot_taken` и откатывает закрытие. Пока у лота остаются просроченные аренды, сотрудник может закрывать их по одной. Лот переходит в выбранный статус после закрытия последней просрочки. Закрытие будущей брони с переводом лота в другой статус в этот период возвращает `409 lot_has_active_rental`.

Списки используют `status`, `limit` и `offset`. Сотруднику дополнительно доступны `user_id`, `lot_id` и фильтры по пересечению с `from` и `to`. Карточка сотрудника возвращает `completed_at` и `closed_by`. Карточка арендатора возвращает связанные тикеты в `tickets` с полями `id`, `category`, `status` и `created_at`. Все ответы аренды используют `Cache-Control: no-store`.

Владелец просматривает и создаёт типы через `GET/POST /admin/batteries`, изменяет количество и удаляет тип через `PATCH/DELETE /admin/batteries/{battery_type}`. При попытке уменьшить количество ниже занятого пика ответ содержит `409 stock_below_committed`, `fields.requested_quantity` и `fields.peak_committed`. Тип, связанный с историей аренд, не удаляется.

### 4.7. Тикеты

| Метод и путь                          | Роли        | Назначение / заметки |
| ------------------------------------- | ----------- | -------------------- |
| `POST /me/rentals/{id}/tickets`       | user+       | Idempotency-Key; лимит за последние 24 ч на аренду → 429 |
| `GET /me/tickets`                     | user+       | `status`, пагинация |
| `GET /me/tickets/{id}`                | user+       | Деталь |
| `GET /admin/tickets`                  | admin, owner| `status`, `lot_id`, `rental_id`, `from`, `to` |
| `GET /admin/tickets/{id}`             | admin, owner| Деталь + фото |
| `PATCH /admin/tickets/{id}`           | admin, owner| `{status, admin_comment, put_lot_maintenance, maintenance_until, version}` |


Подача доступна верифицированному владельцу аренды в статусе `active` или `overdue`. Описание после обрезки пробелов занимает от 10 до 1000 символов. До трёх фото можно загрузить через `POST /files` с `purpose=ticket_photo` и передать их идентификаторы как `file_ids`. Если загрузка не вернула идентификатор, клиент может передать число неудачных загрузок в `photo_upload_failures`. Суммарно принимаются до трёх попыток. Недоступные файлы пропускаются, а `skipped_photo_count` показывает общее число пропусков.

В списках и ответе на обновление `photo_urls` пуст. Успешная подача возвращает квитанцию `TicketReceipt` без описания и контактов. Владелец обращения и сотрудники с правом `tickets.manage` могут получить временные ссылки в соответствующей карточке. Ответы используют `Cache-Control: no-store`. Повтор успешной подачи с тем же ключом возвращает сохранённый ответ. Изменение данных или аренды с тем же ключом даёт `422 idempotency_conflict`.

Сотрудник передаёт версию карточки и переводит её из `submitted` в `in_progress`, затем в `resolved`. Для решения нужен комментарий от трёх символов. Для обслуживания передаются `put_lot_maintenance: true` и будущее время `maintenance_until` с часовым поясом. Статус лота и ограниченный интервал меняются вместе с тикетом. Пересечение с календарём возвращает `409 slot_taken` и оставляет всё без изменений. Ручное возвращение лота закрывает текущий интервал. Автоматический возврат добавляется в BE-WRK-04.

### 4.8. Аналитика (admin, owner)

| Метод и путь                                     | Назначение / заметки |
| ------------------------------------------------ | -------------------- |
| `GET /admin/analytics/summary`                   | KPI за период (`from`,`to`) |
| `GET /admin/analytics/revenue`                   | `group_by` = `category` / `lot` / `day` |
| `GET /admin/analytics/lots/{lot_id}`             | Доходность лота |
| `GET /admin/analytics/utilization`               | Загрузка парка |
| `GET /admin/analytics/compare`                   | `from`, `to`, `compare_from`, `compare_to`; два периода и дельты |
| `GET /admin/analytics/export`                    | `report=rentals`, `format=csv`; поток |

Формулы, доступ и формат выгрузки описаны в [контракте аналитики](../../contract/analytics.md).

### 4.9. Тенант и пользователи (owner)

| Метод и путь                        | Назначение / заметки |
| ----------------------------------- | -------------------- |
| `GET /admin/settings`               | `tenant_settings` + `version` |
| `PATCH /admin/settings`             | Требует `version`; валидация диапазонов §3.8 |
| `GET /admin/users`                  | `role`, `q`, пагинация |
| `POST /admin/users`                 | Создание админа; требуется `mfa_code` (UC-4.7) |
| `POST /admin/users/{id}/deactivate` | Нельзя себя и последнего owner |

Привилегированные операции (не HTTP API):

```text
python -m app.cli provision-tenant --name "Demo Rentals" --slug demo --domain demo.example.com --owner-email owner@example.com
python -m app.cli purge-audit-log [--older-than-days N] [--batch-size N] [--execute]
```

Обе команды требуют `PROVISION_DATABASE_URL` (отдельный привилегированный DSN, не `keep_rollin_app`). Провижининг идемпотентен. Сгенерированный пароль выводится только при первом создании. Флаг «--owner-password-stdin» читает пароль из первой строки stdin и отключает его вывод. В production CLI использует ту же конфигурацию ключей шифрования, что и API. Для удаления записей purge требуется флаг «--execute».
