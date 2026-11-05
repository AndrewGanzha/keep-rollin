import { cancelRentalRequest } from '~/entities/rental'
import { ApiError, useApi } from '~/shared/api'

export const useCancelRental = () => {
  const api = useApi()
  const toast = useToast()
  const pendingId = ref<string | null>(null)

  const cancel = async (id: string): Promise<boolean> => {
    pendingId.value = id

    try {
      await cancelRentalRequest(api, id)
      toast.add({ severity: 'success', summary: 'Бронь отменена', life: 3000 })
      return true
    } catch (caught) {
      const message = caught instanceof ApiError && caught.code === 'cancellation_not_allowed'
        ? 'Отменить бронь уже нельзя по правилам тенанта'
        : 'Не удалось отменить бронь'

      toast.add({ severity: 'error', summary: message, life: 4000 })
      return false
    } finally {
      pendingId.value = null
    }
  }

  return { cancel, pendingId }
}
