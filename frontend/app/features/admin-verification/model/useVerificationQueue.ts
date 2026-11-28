import {
  decideVerificationRequest,
  fetchVerificationRequest,
  fetchVerificationRequests,
  type AdminVerificationRequestSummary,
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

  const deciding = ref(false)
  const detail = shallowRef<VerificationRequest | null>(null)
  const detailError = shallowRef<unknown>(null)
  const detailPending = ref(false)
  let detailRequest: AbortController | undefined

  const clearDetail = () => {
    detailRequest?.abort()
    detailRequest = undefined
    detail.value = null
    detailError.value = null
    detailPending.value = false
  }

  const loadDetail = async (id: string) => {
    clearDetail()
    const controller = new AbortController()
    detailRequest = controller
    detailPending.value = true

    try {
      const received = await fetchVerificationRequest(api, id, controller.signal)
      if (detailRequest === controller) {
        detail.value = received
      }
    } catch (caught) {
      if (detailRequest === controller) {
        detailError.value = caught
      }
    } finally {
      if (detailRequest === controller) {
        detailRequest = undefined
        detailPending.value = false
      }
    }
  }

  onScopeDispose(clearDetail)
  await request

  const decide = async (item: AdminVerificationRequestSummary, payload: VerificationDecisionRequest) => {
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
    detail,
    detailError,
    detailPending,
    loadDetail,
    clearDetail,
  }
}
