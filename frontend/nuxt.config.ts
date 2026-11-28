import { fileURLToPath } from 'node:url'
import Aura from '@primevue/themes/aura'
import type { PrimeVueLocaleOptions } from '@primevue/core/config'
import ru from 'primelocale/ru.json'

const mockOrigin = process.env.MOCK_ORIGIN ?? 'http://127.0.0.1:7777'
const ruLocale = (ru as unknown as { ru: PrimeVueLocaleOptions }).ru

export default defineNuxtConfig({
  compatibilityDate: '2025-07-15',
  devtools: { enabled: false },

  modules: ['@pinia/nuxt', '@primevue/nuxt-module'],

  css: ['primeicons/primeicons.css', '~/assets/styles/main.css'],

  primevue: {
    options: {
      ripple: true,
      locale: ruLocale,
      theme: {
        preset: Aura,
        options: { darkModeSelector: '.app-dark' },
      },
    },
  },

  app: {
    head: {
      htmlAttrs: { lang: 'ru' },
      title: 'Keep Rollin',
      link: [
        { rel: 'manifest', href: '/manifest.webmanifest' },
        { rel: 'apple-touch-icon', href: '/icons/app-192.png' },
      ],
      meta: [
        { name: 'viewport', content: 'width=device-width, initial-scale=1' },
        { name: 'description', content: 'Аренда электробайков и аккумуляторов' },
      ],
    },
  },

  // Override with NUXT_API_PROXY_TARGET on the server (see server/middleware/api-proxy.ts).
  runtimeConfig: {
    apiProxyTarget: '',
    // `localhost` также резолвится в ::1, если dev-сервер слушает только IPv6.
    internalOrigin: 'http://localhost:3000',
  },

  nitro: {
    // Nitro aliases the package root to native fetch. Keep the Node entry explicit.
    alias: { 'node-fetch-native/node': fileURLToPath(import.meta.resolve('node-fetch-native/node')) },
    devProxy: {
      '/api': { target: `${mockOrigin}/api`, changeOrigin: true },
    },
  },

  vite: {
    optimizeDeps: { include: ['openapi-fetch'] },
  },

  typescript: { strict: true },
})
