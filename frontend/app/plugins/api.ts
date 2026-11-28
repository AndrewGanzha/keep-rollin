import { createApiClient } from '~/shared/api'

export default defineNuxtPlugin(async () => {
  const cookie = useCookie<string | null>('kr_token')
  const token = useState<string | null>('access-token', () => cookie.value ?? null)
  // SSR must not call the public origin: behind Ingress/port-forward the Host
  // header is not reachable from inside the pod. Hit this Nitro instance and
  // let server/middleware/api-proxy.ts forward /api to the backend.
  const baseUrl = import.meta.server ? useRuntimeConfig().internalOrigin : ''
  const tenantHost = import.meta.server ? useRequestHeaders(['host']).host : undefined
  // The standard Node fetch replaces an explicit Host with the destination authority.
  const serverFetch = import.meta.server ? (await import('node-fetch-native/node')).fetch : undefined
  const api = createApiClient(baseUrl, () => token.value, tenantHost, serverFetch)

  return { provide: { api } }
})
