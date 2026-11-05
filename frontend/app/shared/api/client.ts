import createClient, { type Client, type Middleware } from 'openapi-fetch'
import type { paths } from './schema'

export type ApiClient = Client<paths>

export const createApiClient = (baseUrl: string, getToken: () => string | null): ApiClient => {
  const client = createClient<paths>({ baseUrl })

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
