# 5. Модель данных: изменения относительно ТЗ §8

> Часть плана MVP. Навигация: [README](../../README.md) · [Контракт](README.md) · [API](api.md) · [Модель данных](data-model.md) · [Задачи](../tasks/README.md) · [Поставка](../delivery.md)

| Изменение | Зачем / какой UC закрывает |
| --------- | -------------------------- |
| **NEW `occupancy`** (lot_id, kind, period `tstzrange`, ref_id, status) + EXCLUDE | Единая защита от пересечений: UC-7.3 A1, UC-2.4, UC-9.4, UC-10.4 (D-11) |
| **NEW `tenant_settings`** | UC-1.7, UC-8.2, лимиты §3.8 |
| **NEW `file` + `attachment`** | Метаданные загрузки и упорядоченные привязки фото к лотам. У файлов и привязок есть RLS и составные FK по тенанту. Существующие публичные URL сохраняются в лоте. Привязки заявок хранятся в `verification_document`. |
| **NEW `refresh_session`, `password_reset_token`, `mfa_challenge`** | D-03 (ротация, reuse detection), D-04 (одноразовый enrollment/login challenge), сброс пароля |
| **NEW `idempotency_key`** | D-08. Композитный ключ по тенанту и пользователю, HMAC нормализованного запроса, JSON успешного ответа, срок 24 часа |
| `user`: `mfa_secret_enc`, `mfa_enabled`, `mfa_last_step`, `mfa_failed_attempts`, `mfa_failure_window_started_at`, `mfa_locked_until`, `mfa_recovery_hashes`, `notification_preferences jsonb`, `is_active` | UC-4.7, UC-11.4; TOTP-секрет шифруется, recovery-коды — keyed-хеши |
| **NEW `verification_request` + `verification_document`** | Паспортные поля в `passport_enc` зашифрованы AES-GCM через существующий `SecretBox`. Контекст связывает шифротекст с тенантом и заявкой. Составные FK связывают документы с заявкой и приватными файлами. Привязанные документы исключаются из очистки непривязанных загрузок. |
| `characteristic.code` (immutable slug) + `is_archived` | Фильтры `char_<code>`, безопасное удаление (UC-1.3) |
| `slug` у `tenant`/`category`/`lot` (unique per tenant) | SEO/SSR, URL (D-18) |
| `offer_version.status` + partial unique `(tenant_id) WHERE status='active'` | UC-4.1 |
| `rental` + `battery_stock` (0015) | Аренда хранит замороженные цену, валюту, вариант и параметры АКБ. Составной FK связывает её с интервалом того же тенанта и лота. Остаток по типу задаётся владельцем. |
| `push_subscription`: unique `(user_id, endpoint)`, `user_agent` | UC-11.2/11.3 |
| **NEW `audit_log`** (append-only, RLS, keyset) | Action enum, actor/role/IP, metadata JSONB без PII, retention: UC-4.6 |
| `user`: индексы `(tenant_id, created_at, id)` и `(tenant_id, role, created_at, id)` | Owner-список администраторов (BE-ADM-01) |
| `tenant_settings`: `vapid_public_key`, `vapid_private_key_enc`, `vapid_key_id` | Провижининг и Web Push (BE-TEN-02) |
| RLS на всех таблицах с `tenant_id`, включая новые | UC-12.3 |
