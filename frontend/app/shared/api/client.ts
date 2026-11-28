import createClient, { type Client, type Middleware } from 'openapi-fetch'
import type { paths } from './schema'

export type ApiClient = Client<paths>

export const createApiClient = (
  baseUrl: string,
  getToken: () => string | null,
  tenantHost?: string,
  serverFetch?: typeof fetch,
): ApiClient => {
  const client = createClient<paths>({
    baseUrl,
    headers: tenantHost ? { host: tenantHost } : undefined,
    fetch: serverFetch
      ? async request => serverFetch(request.url, {
        method: request.method,
        headers: Object.fromEntries(request.headers),
        body: request.body ? await request.arrayBuffer() : undefined,
        signal: request.signal,
        redirect: 'manual',
      })
      : undefined,
  })

  const auth: Middleware = {
    onRequest({ request }) {
      const token = getToken()

      if (token) {
        request.headers.set('Authorization', `Bearer ${token}`)
      }

      return request
    },
  }

  client.use(auth)

  return client
}
