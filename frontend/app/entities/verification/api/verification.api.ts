import { unwrap, type ApiClient } from '~/shared/api'
import type {
  VerificationDecisionRequest,
  VerificationRequest,
  VerificationRequestPage,
  VerificationStatus,
} from '../model/verification.types'

export interface VerificationRequestQuery {
  status?: VerificationStatus
  limit?: number
  offset?: number
}

export const fetchVerificationRequests = async (
  api: ApiClient,
  query: VerificationRequestQuery = {},
): Promise<VerificationRequestPage> =>
  unwrap(await api.GET('/api/v1/admin/verification-requests', { params: { query } }))

export const decideVerificationRequest = async (
  api: ApiClient,
  id: string,
  payload: VerificationDecisionRequest,
): Promise<VerificationRequest> =>
  unwrap(
    await api.POST('/api/v1/admin/verification-requests/{id}/decision', {
      params: { path: { id } },
      body: payload,
    }),
  )
