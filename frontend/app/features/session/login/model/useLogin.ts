import { ApiError } from '~/shared/api'
import { useSession } from '../../model/useSession'

export const useLogin = () => {
  const { login } = useSession()
  const route = useRoute()
  const toast = useToast()

  const pending = ref(false)
  const error = ref<ApiError | null>(null)

  const submit = async (email: string, password: string) => {
    pending.value = true
    error.value = null

    try {
      await login(email, password)
      const next = typeof route.query.next === 'string' ? route.query.next : '/account/rentals'
      await navigateTo(next)
    } catch (caught) {
      error.value = caught instanceof ApiError ? caught : new ApiError({}, 0)
      toast.add({
        severity: 'error',
        summary: 'Не удалось войти',
        detail: error.value.message,
        life: 4000,
      })
    } finally {
      pending.value = false
    }
  }

  return { submit, pending, error }
}
