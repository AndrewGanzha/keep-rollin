# 5. Модель данных: изменения относительно ТЗ §8

> Часть плана MVP. Навигация: [README](../../README.md) · [Контракт](README.md) · [API](api.md) · [Модель данных](data-model.md) · [Задачи](../tasks/README.md) · [Поставка](../delivery.md)

| Изменение | Зачем / какой UC закрывает |
| --------- | -------------------------- |
| **NEW `occupancy`** (lot_id, kind, period `tstzrange`, ref_id, status) + EXCLUDE | Единая защита от пересечений: UC-7.3 A1, UC-2.4, UC-9.4, UC-10.4 (D-11) |
| **NEW `tenant_settings`** | UC-1.7, UC-8.2, лимиты §3.8 |
| **NEW `file` + `attachment`** (вместо `photo_urls jsonb`) | Приватные документы, TTL, лимиты, антивирус-хук: UC-5.3, UC-8.3, UC-1.4 |
| **NEW `refresh_session`, `password_reset_token`** | D-03 (ротация, reuse detection) |
| **NEW `idempotency_key`** | D-08 |
| `user`: `mfa_secret_enc`, `mfa_enabled`, `mfa_recovery_hashes`, `notification_preferences jsonb`, `is_active` | UC-4.7, UC-11.4 |
| `verification_request.passport_data` шифруется (`pgcrypto`), документы — в приватном бакете | Compliance (ТЗ 9.3, Q4) |
| `characteristic.code` (immutable slug) + `is_archived` | Фильтры `char_<code>`, безопасное удаление (UC-1.3) |
| `slug` у `tenant`/`category`/`lot` (unique per tenant) | SEO/SSR, URL (D-18) |
| `offer_version.status` + partial unique `(tenant_id) WHERE status='active'` | UC-4.1 |
| `rental.occupancy_id` FK | Связь брони и занятости |
| `push_subscription`: unique `(user_id, endpoint)`, `user_agent` | UC-11.2/11.3 |
| `audit_log`: enum `action`, `metadata` без PII | UC-4.6 |
| RLS на всех таблицах с `tenant_id`, включая новые | UC-12.3 |
