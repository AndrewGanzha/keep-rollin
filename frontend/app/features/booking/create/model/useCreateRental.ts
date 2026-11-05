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

  const create = async (lotId: string, range: RentalRange): Promise<Rental | null> => {
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
          start_time: range.start.toISOString(),
          end_time: range.end.toISOString(),
        },
        crypto.randomUUID(),
      )

      toast.add({ severity: 'success', summary: 'Бронь создана', life: 3000 })
      await router.push('/account/rentals')
      return rental
    } catch (caught) {
      const message = caught instanceof ApiError && caught.code === 'slot_taken'
        ? 'Этот интервал уже занят — выберите другое время'
        : 'Не удалось создать бронь'

      toast.add({ severity: 'error', summary: message, life: 4000 })
      return null
    } finally {
      pending.value = false
    }
  }

  return { create, pending }
}
