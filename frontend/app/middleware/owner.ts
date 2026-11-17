import { useSession } from '~/features/session/model/useSession'

/** Остатки АКБ — уровень тенанта, раздел доступен только владельцу. */
export default defineNuxtRouteMiddleware(async () => {
  const { load, store } = useSession()
  await load()

  if (store.role !== 'owner') {
    return navigateTo('/admin', { replace: true })
  }
})
