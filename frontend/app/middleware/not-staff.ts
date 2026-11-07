import { useSession } from '~/features/session/model/useSession'

export default defineNuxtRouteMiddleware(async () => {
  const { load, store } = useSession()
  await load()

  if (store.isStaff) {
    return navigateTo('/admin', { replace: true })
  }
})
