import { useSession } from '~/features/session/model/useSession'

export default defineNuxtRouteMiddleware(async () => {
  const { load, store } = useSession()
  await load()

  if (!store.isStaff) {
    throw createError({
      statusCode: 403,
      statusMessage: 'Раздел доступен только администраторам',
    })
  }
})
