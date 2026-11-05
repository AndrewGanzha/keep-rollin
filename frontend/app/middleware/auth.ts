import { useSession } from '~/features/session/model/useSession'

export default defineNuxtRouteMiddleware(async (to) => {
  const { load, store } = useSession()
  await load()

  if (!store.isAuthenticated) {
    return navigateTo({ path: '/login', query: { next: to.fullPath } })
  }
})
