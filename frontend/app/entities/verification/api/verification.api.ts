import { unwrap, type ApiClient } from '~/shared/api'
import type {
  AdminVerificationRequestSummary,
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

export const fetchVerificationRequest = async (
  api: ApiClient,
  id: string,
  signal: AbortSignal,
): Promise<VerificationRequest> =>
  unwrap(await api.GET('/api/v1/admin/verification-requests/{id}', {
    params: { path: { id } },
    cache: 'no-store',
    signal,
  }))

export const decideVerificationRequest = async (
  api: ApiClient,
  id: string,
  payload: VerificationDecisionRequest,
): Promise<AdminVerificationRequestSummary> =>
  unwrap(
    await api.POST('/api/v1/admin/verification-requests/{id}/decision', {
      params: { path: { id } },
      body: payload,
    }),
  )
