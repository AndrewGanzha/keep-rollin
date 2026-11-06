import {
  cancelAdminRental,
  closeAdminRental,
  fetchAdminRentals,
  type AdminRental,
  type AdminRentalStatus,
  type CancelAdminRentalRequest,
  type CloseRentalRequest,
} from '~/entities/rental'
import { useTenant } from '~/entities/tenant'
import { ApiError, useApi } from '~/shared/api'
import { calendarRange, dayKeyOf, type CalendarView } from '~/shared/lib'

export const useAdminRentals = async () => {
  const api = useApi()
  const toast = useToast()
  const tenant = useTenant()

  const timeZone = computed(() => tenant.value?.timezone)
  const todayKey = computed(() => dayKeyOf(new Date(), timeZone.value))

  const view = ref<CalendarView>('day')
  const anchor = ref(todayKey.value)
  const status = ref<AdminRentalStatus | undefined>()
  const selected = ref<AdminRental | null>(null)
  const range = computed(() => calendarRange(view.value, anchor.value, timeZone.value))

  const request = useAsyncData(
    'admin-rentals',
    () => fetchAdminRentals(api, {
      status: status.value,
      from: range.value.from,
      to: range.value.to,
      limit: 100,
    }),
    { watch: [status, range] },
  )
  await request

  const acting = ref(false)

  const run = async (action: () => Promise<unknown>, summary: string): Promise<boolean> => {
    acting.value = true

    try {
      await action()
      toast.add({ severity: 'success', summary, life: 3000 })
      await request.refresh()
      return true
    } catch (caught) {
      const message = caught instanceof ApiError ? caught.message : 'Не удалось выполнить действие'
      toast.add({ severity: 'error', summary: message, life: 4000 })
      return false
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
    timeZone,
    todayKey,
    view,
    anchor,
    status,
    selected,
    acting,
    close,
    cancel,
  }
}
