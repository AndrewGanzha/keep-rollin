# 4. Каталог эндпоинтов (контракт)

> Часть плана MVP. Навигация: [README](../../README.md) · [Контракт](README.md) · [API](api.md) · [Модель данных](data-model.md) · [Задачи](../tasks/README.md) · [Поставка](../delivery.md)

Роли: `гость` — без токена; `user`, `admin`, `owner` — см. §3.3. Все пути с префиксом `/api/v1`.

### 4.1. Публичные и сессия

| Метод и путь                              | Роли  | Назначение / заметки |
| ----------------------------------------- | ----- | -------------------- |
| `GET /public/tenant`                      | гость | Брендинг, tz, currency, контакты, policies, `vapid_public_key` |
| `GET /public/categories`                  | гость | Активные категории + характеристики + счётчики лотов |
| `GET /public/lots`                        | гость | Фильтры `category_id`, `char_<code>`, `available_from/to`, `sort`; только `active` |
| `GET /public/lots/{slug}`                 | гость | Карточка; 404 для `archived`/`maintenance`/`overdue` |
| `GET /public/lots/{slug}/availability`    | гость | §3.7 |
| `GET /public/availability`                | гость | Агрегат по категории/модели (UC-2.2) |
| `GET /public/offers/current`              | гость | Активная версия оферты (текст + версия) |
| `GET /health`, `GET /readyz`, `GET /metrics` | infra | Liveness / readiness / Prometheus |

### 4.2. Аутентификация и профиль

| Метод и путь                     | Роли  | Назначение / заметки |
| -------------------------------- | ----- | -------------------- |
| `POST /auth/register`            | гость | email+phone+password → 201 + токены |
| `POST /auth/login`               | гость | → токены или `mfa_required` |
| `POST /auth/mfa/verify`          | гость | `mfa_token` + код → токены |
| `POST /auth/mfa/setup`           | owner/admin | Секрет + otpauth-URI |
| `POST /auth/mfa/confirm`         | owner/admin | Код → recovery-коды |
| `POST /auth/refresh`             | cookie | Ротация refresh |
| `POST /auth/logout`              | все   | Отзыв сессии, очистка cookie |
| `POST /auth/password/forgot`     | гость | Всегда 202 (без enumeration) |
| `POST /auth/password/reset`      | гость | Токен + новый пароль |
| `GET /auth/session`              | все   | user, tenant, role, `permissions[]`, `verification_status`, `offer_accepted`, prefs-summary |
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
