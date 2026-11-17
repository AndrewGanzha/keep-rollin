import { fetchCategories } from '~/entities/category'
import {
  createLot,
  fetchAdminLots,
  setLotStatus,
  updateLot,
  type CreateLotRequest,
  type Lot,
  type LotStatus,
  type LotStatusRequest,
} from '~/entities/lot'
import { ApiError, useApi } from '~/shared/api'

export const useAdminLots = async () => {
  const api = useApi()
  const toast = useToast()

  const status = ref<LotStatus | undefined>()

  const request = useAsyncData(
    'admin-lots',
    () => fetchAdminLots(api, { status: status.value, limit: 100 }),
    { watch: [status] },
  )
  const categoriesRequest = useAsyncData('admin-lots-categories', () => fetchCategories(api))

  await Promise.all([request, categoriesRequest])

  const saving = ref(false)
  const updating = ref(false)
  const fields = ref<Record<string, string>>({})

  /** Создание или правка лота; `version` для PATCH берётся из переданного лота. */
  const save = async (payload: CreateLotRequest, lot?: Lot | null): Promise<Lot | null> => {
    saving.value = true
    fields.value = {}

    try {
      const saved = lot
        ? await updateLot(api, lot.id, { ...payload, version: lot.version })
        : await createLot(api, payload)

      toast.add({
        severity: 'success',
        summary: lot ? `Лот «${saved.name}» обновлён` : `Лот «${saved.name}» создан`,
        life: 3000,
      })
      await request.refresh()
      return saved
    } catch (caught) {
      if (caught instanceof ApiError) {
        fields.value = caught.fields

        if (caught.code === 'stale_version') {
          toast.add({
            severity: 'warn',
            summary: 'Лот изменён другим администратором — данные обновлены',
            life: 5000,
          })
          await request.refresh()
        } else {
          toast.add({ severity: 'error', summary: caught.message, life: 4000 })
        }
      } else {
        toast.add({ severity: 'error', summary: 'Не удалось сохранить лот', life: 4000 })
      }

      return null
    } finally {
      saving.value = false
    }
  }

  const updateStatus = async (
    lot: Lot,
    status: LotStatusRequest['status'],
  ): Promise<boolean> => {
    updating.value = true

    try {
      await setLotStatus(api, lot.id, { status })
      toast.add({ severity: 'success', summary: `Статус лота «${lot.name}» изменён`, life: 3000 })
      await request.refresh()
      return true
    } catch (caught) {
      const message = caught instanceof ApiError ? caught.message : 'Не удалось изменить статус'
      toast.add({ severity: 'error', summary: message, life: 4000 })
      return false
    } finally {
      updating.value = false
    }
  }

  return {
    data: request.data,
    pending: request.pending,
    error: request.error,
    refresh: request.refresh,
    status,
    categories: categoriesRequest.data,
    fields,
    saving,
    save,
    updating,
    updateStatus,
  }
}
