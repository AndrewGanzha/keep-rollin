import { fetchBatteryStock, updateBatteryStock, type BatteryStock } from '~/entities/battery'
import { ApiError, useApi } from '~/shared/api'

/**
 * Остатки АКБ тенанта (D-23). Пик занятости сервер считает сам;
 * клиент держит только черновики количества и перечитывает данные после правки.
 */
export const useAdminBatteries = async () => {
  const api = useApi()
  const toast = useToast()

  const request = useAsyncData('admin-batteries', () => fetchBatteryStock(api))
  await request

  const drafts = ref<Record<string, number>>({})
  const saving = ref<string | null>(null)

  watch(request.data, (items) => {
    drafts.value = Object.fromEntries((items ?? []).map(item => [item.battery_type, item.quantity]))
  }, { immediate: true })

  const setDraft = (batteryType: string, quantity: number | null) => {
    if (quantity !== null) {
      drafts.value[batteryType] = quantity
    }
  }

  const save = async (item: BatteryStock): Promise<boolean> => {
    const quantity = drafts.value[item.battery_type]

    if (quantity === undefined || quantity === item.quantity) {
      return false
    }

    saving.value = item.battery_type

    try {
      const saved = await updateBatteryStock(api, item.battery_type, { quantity })

      toast.add({
        severity: 'success',
        summary: `${item.name}: остаток ${saved.quantity} шт.`,
        life: 3000,
      })
      await request.refresh()

      return true
    } catch (caught) {
      if (caught instanceof ApiError) {
        toast.add({
          severity: 'error',
          summary: caught.code === 'stock_below_committed'
            ? caught.fields.quantity ?? 'Нельзя уменьшить остаток: часть аккумуляторов уже забронирована'
            : 'Не удалось сохранить остаток',
          life: 5000,
        })
      }

      await request.refresh()

      return false
    } finally {
      saving.value = null
    }
  }

  return {
    data: request.data,
    pending: request.pending,
    error: request.error,
    refresh: request.refresh,
    drafts,
    saving,
    setDraft,
    save,
  }
}
