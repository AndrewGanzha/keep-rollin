import type { ApiClient } from './client'

/** Клиент, привязанный к текущему запросу (SSR) или к браузеру. */
export const useApi = (): ApiClient => useNuxtApp().$api
