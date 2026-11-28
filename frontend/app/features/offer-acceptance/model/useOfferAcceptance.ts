import { acceptOffer } from '~/entities/offer'
import { useSessionStore } from '~/entities/session'
import { ApiError, useApi } from '~/shared/api'
import { offerReturn } from './offer-return'
import { useCurrentOffer } from './useCurrentOffer'

export const useOfferAcceptance = () => {
  const api = useApi()
  const session = useSessionStore()
  const route = useRoute()
  const router = useRouter()
  const current = useCurrentOffer('account-current-offer')
  const offer = computed(() => current.data.value?.offer)
  const next = computed(() => offerReturn(route.query.next))
  const accepting = ref(false)
  const notice = ref('')

  const accept = async () => {
    const shown = offer.value
    const userId = session.user?.id
    if (!shown || !userId || accepting.value || current.pending.value) return
    accepting.value = true
    notice.value = ''
    try {
      await acceptOffer(api, shown.id)
      if (session.user?.id === userId) {
        session.markOfferAccepted(userId)
        await router.replace(next.value)
      }
    } catch (error) {
      if (error instanceof ApiError && (error.code === 'offer_not_active' || error.status === 404)) {
        await current.refresh()
        notice.value = 'Версия оферты изменилась. Ознакомьтесь с новым текстом.'
      } else {
        notice.value = 'Не удалось принять оферту. Попробуйте ещё раз.'
      }
    } finally {
      accepting.value = false
    }
  }

  return { current, offer, next, accepting, notice, accept }
}
