import { useSession } from '~/features/session/model/useSession'

export default defineNuxtPlugin(async () => {
  const { load } = useSession()
  await load()
})
