import { createApiClient } from '~/shared/api'

export default defineNuxtPlugin(() => {
  const cookie = useCookie<string | null>('kr_token')
  const token = useState<string | null>('access-token', () => cookie.value ?? null)
  // SSR must not call the public origin: behind Ingress/port-forward the Host
  // header is not reachable from inside the pod. Hit this Nitro instance and
  // let server/middleware/api-proxy.ts forward /api to the backend.
  const baseUrl = import.meta.server ? useRuntimeConfig().internalOrigin : ''
  const api = createApiClient(baseUrl, () => token.value)

  return { provide: { api } }
})
