import {
  cancelAdminRental,
  closeAdminRental,
  fetchAdminRentals,
  type AdminRental,
  type AdminRentalStatus,
  type CancelAdminRentalRequest,
  type CloseRentalRequest,
} from '~/entities/rental'
import { ApiError, useApi } from '~/shared/api'

export const useAdminRentals = async () => {
  const api = useApi()
  const toast = useToast()
  const status = ref<AdminRentalStatus | undefined>()

  const request = useAsyncData(
    'admin-rentals',
    () => fetchAdminRentals(api, { status: status.value }),
    { watch: [status] },
  )
  await request

  const acting = ref(false)

  const run = async (action: () => Promise<unknown>, summary: string) => {
    acting.value = true

    try {
      await action()
      toast.add({ severity: 'success', summary, life: 3000 })
      await request.refresh()
    } catch (caught) {
      const message = caught instanceof ApiError ? caught.message : 'Не удалось выполнить действие'
      toast.add({ severity: 'error', summary: message, life: 4000 })
    } finally {
      acting.value = false
    }
  }

  const close = (rental: AdminRental, payload: CloseRentalRequest) =>
    run(() => closeAdminRental(api, rental.id, payload), 'Аренда закрыта')

  const cancel = (rental: AdminRental, payload: CancelAdminRentalRequest) =>
    run(() => cancelAdminRental(api, rental.id, payload), 'Аренда отменена')

  return {
    data: request.data,
    pending: request.pending,
    error: request.error,
    refresh: request.refresh,
    status,
    acting,
    close,
    cancel,
  }
}
