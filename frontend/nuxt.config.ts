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
      meta: [
        { name: 'viewport', content: 'width=device-width, initial-scale=1' },
        { name: 'description', content: 'Аренда электробайков и аккумуляторов' },
      ],
    },
  },

  // Override with NUXT_API_PROXY_TARGET on the server (see server/middleware/api-proxy.ts).
  runtimeConfig: {
    apiProxyTarget: '',
    internalOrigin: 'http://127.0.0.1:3000',
  },

  nitro: {
    devProxy: {
      '/api': { target: `${mockOrigin}/api`, changeOrigin: true },
    },
  },

  vite: {
    optimizeDeps: { include: ['openapi-fetch'] },
  },

  typescript: { strict: true },
})
