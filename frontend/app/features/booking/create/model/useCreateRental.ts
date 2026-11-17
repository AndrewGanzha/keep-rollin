import { createRentalRequest, type Rental } from '~/entities/rental'
import { useSessionStore } from '~/entities/session'
import { ApiError, useApi } from '~/shared/api'

export interface RentalRange {
  start: Date
  end: Date
}

export const useCreateRental = () => {
  const api = useApi()
  const session = useSessionStore()
  const toast = useToast()
  const router = useRouter()

  const pending = ref(false)

  const create = async (
    lotId: string,
    variantId: string,
    range: RentalRange,
    onError?: (code: string) => void,
  ): Promise<Rental | null> => {
    if (pending.value) {
      return null
    }

    if (!session.isAuthenticated) {
      await router.push({ path: '/login', query: { next: router.currentRoute.value.fullPath } })
      return null
    }

    pending.value = true

    try {
      const rental = await createRentalRequest(
        api,
        {
          lot_id: lotId,
          variant_id: variantId,
          start_time: range.start.toISOString(),
          end_time: range.end.toISOString(),
        },
        crypto.randomUUID(),
      )

      toast.add({ severity: 'success', summary: 'Бронь создана', life: 3000 })
      await router.push('/account/rentals')
      return rental
    } catch (caught) {
      const code = caught instanceof ApiError ? caught.code : ''
      const message = code === 'slot_taken'
        ? 'Этот интервал уже занят — выберите другое время'
        : code === 'battery_unavailable'
          ? 'Свободных аккумуляторов на эти даты нет'
          : code === 'rental_period_not_allowed'
            ? 'Срок короче минимального — увеличьте длительность'
            : 'Не удалось создать бронь'

      toast.add({ severity: 'error', summary: message, life: 4000 })
      onError?.(code)
      return null
    } finally {
      pending.value = false
    }
  }

  return { create, pending }
}
