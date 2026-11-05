import { fetchSession, loginRequest, useSessionStore } from '~/entities/session'
import { useApi } from '~/shared/api'

/**
 * Сессия: единственное место, где читается/пишется токен
 * и синхронизируется Pinia-стор. Вызывается из плагина и middleware.
 */
export const useSession = () => {
  const api = useApi()
  const store = useSessionStore()
  const cookie = useCookie<string | null>('kr_token', {
    maxAge: 60 * 60 * 24,
    sameSite: 'lax',
    path: '/',
  })
  const token = useState<string | null>('access-token', () => cookie.value ?? null)
  const loaded = useState('session-loaded', () => false)

  const setToken = (value: string | null) => {
    token.value = value
    cookie.value = value
  }

  const load = async (force = false) => {
    if (loaded.value && !force) {
      return
    }

    if (!token.value) {
      store.clear()
      loaded.value = true
      return
    }

    try {
      store.setSession(await fetchSession(api))
    } catch {
      setToken(null)
      store.clear()
    } finally {
      loaded.value = true
    }
  }

  const login = async (email: string, password: string) => {
    const response = await loginRequest(api, { email, password })
    setToken(response.access_token)
    loaded.value = false
    await load(true)
  }

  const logout = () => {
    setToken(null)
    store.clear()
    loaded.value = true
  }

  return { store, load, login, logout }
}
