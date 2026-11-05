import {
  decideVerificationRequest,
  fetchVerificationRequests,
  type VerificationDecisionRequest,
  type VerificationRequest,
  type VerificationStatus,
} from '~/entities/verification'
import { ApiError, useApi } from '~/shared/api'

export const useVerificationQueue = async () => {
  const api = useApi()
  const toast = useToast()
  const status = ref<VerificationStatus | undefined>('pending')

  const request = useAsyncData(
    'admin-verification',
    () => fetchVerificationRequests(api, { status: status.value }),
    { watch: [status] },
  )
  await request

  const deciding = ref(false)

  const decide = async (item: VerificationRequest, payload: VerificationDecisionRequest) => {
    deciding.value = true

    try {
      await decideVerificationRequest(api, item.id, payload)
      toast.add({ severity: 'success', summary: 'Решение сохранено', life: 3000 })
      await request.refresh()
    } catch (caught) {
      const message = caught instanceof ApiError ? caught.message : 'Не удалось сохранить решение'
      toast.add({ severity: 'error', summary: message, life: 4000 })
      await request.refresh()
    } finally {
      deciding.value = false
    }
  }

  return {
    data: request.data,
    pending: request.pending,
    error: request.error,
    refresh: request.refresh,
    status,
    deciding,
    decide,
  }
}
