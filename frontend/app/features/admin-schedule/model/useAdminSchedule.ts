import {
  cancelAdminRental,
  closeAdminRental,
  type AdminRental,
  type CancelAdminRentalRequest,
  type CloseRentalRequest,
} from '~/entities/rental'
import {
  createLotBlock,
  deleteLotBlock,
  fetchSchedule,
  type ScheduleBlockInterval,
  type ScheduleRentalInterval,
} from '~/entities/schedule'
import { useTenant } from '~/entities/tenant'
import { ApiError, unwrap, useApi } from '~/shared/api'
import { blockRangeIso, dayKeyOf, monthDays, shiftMonth } from '~/shared/lib'

export const useAdminSchedule = async () => {
  const api = useApi()
  const toast = useToast()
  const tenant = useTenant()

  const timeZone = computed(() => tenant.value?.timezone)
  const todayKey = computed(() => dayKeyOf(new Date(), timeZone.value))
  const anchor = ref(todayKey.value)

  const from = computed(() => shiftMonth(anchor.value, 0))
  const to = computed(() => shiftMonth(anchor.value, 1))
  const days = computed(() => monthDays(anchor.value))

  const monthLabel = computed(() => new Intl.DateTimeFormat('ru-RU', {
    month: 'long',
    year: 'numeric',
    timeZone: 'UTC',
  }).format(new Date(`${from.value}T00:00:00.000Z`)))

  const request = useAsyncData(
    'admin-schedule',
    () => fetchSchedule(api, { from: from.value, to: to.value }),
    { watch: [from, to] },
  )
  await request

  const saving = ref(false)
  const acting = ref(false)

  const shift = (direction: number) => {
    anchor.value = shiftMonth(anchor.value, direction)
  }

  const createBlock = async (
    lotId: string,
    fromDay: string,
    toDay: string,
    reason: string,
  ): Promise<boolean> => {
    saving.value = true

    try {
      const range = blockRangeIso(fromDay, toDay, timeZone.value)

      await createLotBlock(api, lotId, {
        start_time: range.start,
        end_time: range.end,
        reason: reason.trim(),
      })
      toast.add({ severity: 'success', summary: 'Дни заблокированы', life: 3000 })
      await request.refresh()
      return true
    } catch (caught) {
      const message = caught instanceof ApiError
        ? caught.code === 'slot_taken'
          ? 'В эти дни лот занят'
          : caught.message
        : 'Не удалось заблокировать дни'
      toast.add({ severity: 'error', summary: message, life: 4000 })
      return false
    } finally {
      saving.value = false
    }
  }

  const removeBlock = async (block: ScheduleBlockInterval): Promise<boolean> => {
    saving.value = true

    try {
      await deleteLotBlock(api, block.lot_id, block.block_id)
      toast.add({ severity: 'success', summary: 'Блокировка снята', life: 3000 })
      await request.refresh()
      return true
    } catch (caught) {
      const message = caught instanceof ApiError ? caught.message : 'Не удалось снять блокировку'
      toast.add({ severity: 'error', summary: message, life: 4000 })
      return false
    } finally {
      saving.value = false
    }
  }

  const openRental = async (interval: ScheduleRentalInterval): Promise<AdminRental | null> => {
    try {
      return unwrap(await api.GET('/api/v1/admin/rentals/{id}', {
        params: { path: { id: interval.rental_id } },
      }))
    } catch (caught) {
      const message = caught instanceof ApiError
        ? caught.code === 'not_found' ? 'Аренда не найдена' : caught.message
        : 'Не удалось открыть аренду'
      toast.add({ severity: 'error', summary: message, life: 4000 })
      return null
    }
  }

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
    anchor,
    from,
    to,
    days,
    monthLabel,
    shift,
    saving,
    acting,
    createBlock,
    removeBlock,
    openRental,
    close,
    cancel,
  }
}
