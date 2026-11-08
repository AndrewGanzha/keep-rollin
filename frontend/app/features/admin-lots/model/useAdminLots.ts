import { fetchCategories } from '~/entities/category'
import {
  createLot,
  fetchAdminLots,
  setLotStatus,
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

  const creating = ref(false)
  const updating = ref(false)

  const create = async (payload: CreateLotRequest): Promise<Lot | null> => {
    creating.value = true

    try {
      const lot = await createLot(api, payload)
      toast.add({ severity: 'success', summary: `Лот «${lot.name}» создан`, life: 3000 })
      await request.refresh()
      return lot
    } catch (caught) {
      const message = caught instanceof ApiError ? caught.message : 'Не удалось создать лот'
      toast.add({ severity: 'error', summary: message, life: 4000 })
      return null
    } finally {
      creating.value = false
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
    creating,
    create,
    updating,
    updateStatus,
  }
}
