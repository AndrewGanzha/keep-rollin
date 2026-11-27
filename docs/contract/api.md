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
| `GET /auth/session`              | все   | user, tenant, role, `permissions[]`, `verification_status`, `offer_accepted`, `mfa_enabled` (`prefs-summary` — follow-up BE-NOT-04) |
| `GET /me/push-subscriptions`     | user+ | Список подписок |
| `POST /me/push-subscriptions`    | user+ | Upsert по `endpoint` |
| `DELETE /me/push-subscriptions/{id}` | user+ | Отписка |
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
| `POST /admin/lots/{id}/status`                    | `active`/`archived`/`maintenance`; guard UC-1.5 |
| `POST /admin/lots/bulk`                           | `count ≤ 50`, Idempotency-Key |
| `POST /admin/lots/{id}/blocks`                    | Ручная блокировка (UC-2.4) |
| `DELETE /admin/lots/{id}/blocks/{block_id}`       | Снять блокировку |
| `POST /files`                                     | multipart, `purpose`; → `file_id` + подписанный URL |

### 4.4. Календарь и доступность (staff)

| Метод и путь                  | Роли        | Назначение / заметки |
| ----------------------------- | ----------- | -------------------- |
| `GET /admin/calendar`         | admin, owner | `from`, `to`, `category_id`, `lot_id`, `status`; ≤ 200 лотов |
| `GET /admin/lots/{id}/calendar` | admin, owner | Детальный календарь лота с rental/block |

### 4.5. Верификация и оферта

> Маршруты `verification-requests` ниже — planned: BE-VER-01/02/03 ещё не реализованы, поэтому их нет в текущем `contract/openapi.json`. Оферты реализованы.

| Метод и путь                                    | Роли        | Назначение / заметки |
| ----------------------------------------------- | ----------- | -------------------- |
| `POST /me/verification-requests`                | user+       | Паспортные данные + 3 документа; Idempotency-Key |
| `GET /me/verification-requests`                 | user+       | История заявок |
| `GET /me/verification-requests/{id}`            | user+       | Статус + комментарий |
| `GET /admin/verification-requests`              | admin, owner| Очередь, фильтр `status`, пагинация |
| `GET /admin/verification-requests/{id}`         | admin, owner| Деталь + подписанные URL документов (5 мин) |
| `POST /admin/verification-requests/{id}/decision` | admin, owner | `{decision, comment, version}`; 409 `already_processed` |
| `GET /admin/audit-log`                          | owner       | Фильтры по актору/сущности/дате, keyset-пагинация |
| `GET /admin/offers`                             | owner       | Версии оферты |
| `POST /admin/offers`                            | owner       | Новая версия (draft) |
| `PATCH /admin/offers/{id}`                      | owner       | Правка draft |
| `POST /admin/offers/{id}/publish`               | owner       | Активирует, прежняя → `archived` |
| `POST /me/offer-acceptances`                    | user+       | `{offer_version_id}`; идемпотентно |
| `GET /me/offer-acceptances`                     | user+       | История принятий |

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

### 4.7. Тикеты

| Метод и путь                          | Роли        | Назначение / заметки |
| ------------------------------------- | ----------- | -------------------- |
| `POST /me/rentals/{id}/tickets`       | user+       | Idempotency-Key; лимит 5/сутки/аренда → 429 |
| `GET /me/tickets`                     | user+       | `status`, пагинация |
| `GET /me/tickets/{id}`                | user+       | Деталь |
| `GET /admin/tickets`                  | admin, owner| `status`, `lot_id`, `rental_id`, `from`, `to` |
| `GET /admin/tickets/{id}`             | admin, owner| Деталь + фото |
| `PATCH /admin/tickets/{id}`           | admin, owner| `{status, admin_comment, put_lot_maintenance, maintenance_until, version}` |

### 4.8. Аналитика (admin, owner)

| Метод и путь                                     | Назначение / заметки |
| ------------------------------------------------ | -------------------- |
| `GET /admin/analytics/summary`                   | KPI за период (`from`,`to`) |
| `GET /admin/analytics/revenue`                   | `group_by` = `category` / `lot` / `day` |
| `GET /admin/analytics/lots/{lot_id}`             | Доходность лота |
| `GET /admin/analytics/utilization`               | Загрузка парка |
| `GET /admin/analytics/compare`                   | Два периода, дельты |
| `GET /admin/analytics/export`                    | `report`, `format=csv`; поток |

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
