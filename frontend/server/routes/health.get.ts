/** Liveness probe for Docker/Caddy. Must not touch the API. */
export default defineEventHandler(() => ({ status: 'ok' }))
