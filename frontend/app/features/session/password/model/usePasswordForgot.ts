import { requestPasswordReset } from '~/entities/session'
import { useApi } from '~/shared/api'

export const usePasswordForgot = () => {
  const api = useApi()
  const email = ref('')
  const pending = ref(false)
  const sent = ref(false)
  const failed = ref(false)

  const submit = async () => {
    if (pending.value) return
    pending.value = true
    failed.value = false
    try {
      await requestPasswordReset(api, { email: email.value.trim() })
      sent.value = true
      email.value = ''
    } catch {
      failed.value = true
    } finally {
      pending.value = false
    }
  }

  return { email, pending, sent, failed, submit }
}
