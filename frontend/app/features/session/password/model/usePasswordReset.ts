import { resetPassword } from '~/entities/session'
import { ApiError, useApi } from '~/shared/api'
import { useSession } from '../../model/useSession'
import { readPasswordResetToken } from './reset-token'

export const usePasswordReset = () => {
  const api = useApi()
  const { load } = useSession()
  const route = useRoute()
  const router = useRouter()
  const token = shallowRef<string | null>(null)
  const ready = ref(false)
  const password = ref('')
  const confirmation = ref('')
  const pending = ref(false)
  const completed = ref(false)
  const error = ref('')

  onMounted(async () => {
    const { token: legacyToken, ...query } = route.query
    token.value = readPasswordResetToken(legacyToken, route.hash)
    if (legacyToken !== undefined || route.hash) {
      await router.replace({ path: route.path, query })
    }
    ready.value = true
  })

  const submit = async () => {
    if (!token.value || pending.value) return
    error.value = ''
    const length = [...password.value].length
    if (length < 8 || length > 128) {
      error.value = 'Введите пароль длиной от 8 до 128 символов.'
      return
    }
    if (password.value !== confirmation.value) {
      error.value = 'Пароли не совпадают.'
      return
    }
    pending.value = true
    try {
      await resetPassword(api, { token: token.value, password: password.value })
      await load(true)
      completed.value = true
      token.value = null
      password.value = ''
      confirmation.value = ''
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 401) {
        token.value = null
        password.value = ''
        confirmation.value = ''
      } else {
        error.value = caught instanceof ApiError && caught.status === 422
          ? 'Выберите другой пароль.'
          : 'Не удалось сохранить пароль. Попробуйте ещё раз.'
      }
    } finally {
      pending.value = false
    }
  }

  return { token, ready, password, confirmation, pending, completed, error, submit }
}
