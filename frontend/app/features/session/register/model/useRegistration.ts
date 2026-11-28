import { acceptOffer } from '~/entities/offer'
import { registerRequest } from '~/entities/session'
import { offerGateLocation, useCurrentOffer } from '~/features/offer-acceptance'
import { ApiError, useApi } from '~/shared/api'
import { registrationCredentials } from '../../model/credentials'
import { useSession } from '../../model/useSession'

const verification = '/account/verification'

export const useRegistration = () => {
  const api = useApi()
  const router = useRouter()
  const { establish, store } = useSession()
  const current = useCurrentOffer('registration-current-offer')
  const offer = computed(() => current.data.value?.offer)
  const values = reactive({ email: '', password: '', name: '', phone: '' })
  const consentedOffer = ref<string | null>(null)
  const consent = computed({
    get: () => Boolean(offer.value && consentedOffer.value === offer.value.id),
    set: checked => { consentedOffer.value = checked ? offer.value?.id ?? null : null },
  })
  const pending = ref(false)
  const created = ref(false)
  const message = ref('')
  const fields = ref<Partial<Record<keyof typeof values, string>>>({})
  const login = { path: '/login', query: { next: router.resolve(offerGateLocation(verification)).fullPath } }

  const submit = async () => {
    if (created.value || pending.value || current.pending.value || current.error.value || offer.value === undefined) return
    message.value = ''
    fields.value = {}
    const input = registrationCredentials.safeParse(values)
    if (!input.success) {
      for (const issue of input.error.issues) {
        const key = issue.path[0] as keyof typeof values
        fields.value[key] ??= issue.message
      }
      return
    }
    const shown = offer.value
    if (shown && consentedOffer.value !== shown.id) {
      message.value = 'Ознакомьтесь с офертой и подтвердите согласие.'
      return
    }

    pending.value = true
    try {
      const result = await registerRequest(api, input.data)
      created.value = true
      values.password = ''
      if (!result.access_token) throw new Error('Missing access token')
      await establish(result.access_token)
    } catch (error) {
      if (created.value) {
        message.value = 'Аккаунт создан. Войдите, чтобы продолжить.'
      } else if (error instanceof ApiError && error.code === 'email_taken') {
        fields.value.email = 'Аккаунт с таким email уже существует.'
      } else if (error instanceof ApiError && error.fields.password) {
        fields.value.password = 'Выберите другой пароль.'
      } else {
        message.value = 'Не удалось зарегистрироваться. Проверьте данные и попробуйте ещё раз.'
      }
      pending.value = false
      return
    }

    try {
      if (shown) {
        const userId = store.user?.id
        await acceptOffer(api, shown.id)
        if (userId) store.markOfferAccepted(userId)
      }
      await router.replace(verification)
    } catch {
      await router.replace(offerGateLocation(verification))
    } finally {
      pending.value = false
    }
  }

  return { values, fields, current, offer, consent, message, pending, created, login, submit }
}
