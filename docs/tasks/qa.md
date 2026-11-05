# 6.4. Окружение и приёмка

> Часть плана MVP. Навигация: [README](../../README.md) · [Контракт](../contract/README.md) · [API](../contract/api.md) · [Модель данных](../contract/data-model.md) · [Задачи](README.md) · [Поставка](../delivery.md)

## 6.4.1. Окружение и seed

_Подгруппа **Q1** · 1 задача._

### QA-00 · Full-stack окружение и seed

**Зависит:** BE-03, FE-00
**Объём:** compose (postgres, minio, mailhog, api, worker, web), `make seed`: 2 категории, 6 лотов, owner/admin/user, заявки, аренды во всех статусах; `pnpm dev:full` поднимает mock-config-server + Nuxt без БД и backend.
**AC:**
- [ ] `make up && make seed` даёт рабочий стенд с демо-данными.
- [x] `pnpm dev:full` поднимает FE на моке без БД и backend (frontend-first).
- [ ] Smoke-тест логина и публичного каталога зелёный.

## 6.4.2. Приёмка MVP

_Подгруппа **Q2** · 1 задача._

### QA-01 · Приёмка MVP

**Зависит:** все
**Объём:** прогон 12 критериев Приложения D ТЗ с доказательствами.
**AC:** [ ] На каждый пункт — ссылка на e2e-тест/скрин/лог. [ ] Открытые отклонения оформлены как задачи с приоритетом.
