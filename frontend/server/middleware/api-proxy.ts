/**
 * Production proxy for same-origin `/api/**` calls.
 *
 * The browser and SSR client always call the Nuxt origin; without a target the
 * request falls through to Nuxt routing (which 404s). Set NUXT_API_PROXY_TARGET
 * on the server to forward to the real backend. In dev `nitro.devProxy` handles
 * `/api` to the mock server, and this middleware is a no-op.
 */
export default defineEventHandler((event) => {
  if (!event.path.startsWith('/api/')) {
    return
  }

  const target = useRuntimeConfig(event).apiProxyTarget

  if (!target) {
    if (import.meta.dev) {
      // nitro.devProxy owns /api in development.
      return
    }
    // Never fall through to Nuxt: SSR of an unhandled /api request would run
    // app/plugins/tenant.ts again, fetch /api, and recurse until OOM.
    throw createError({ statusCode: 404, statusMessage: 'API proxy is not configured' })
  }

  return proxyRequest(event, `${target.replace(/\/$/, '')}${event.path}`)
})
