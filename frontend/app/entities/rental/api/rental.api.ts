import { unwrap, type ApiClient } from '~/shared/api'
import type { CreateRentalRequest, Rental, RentalPage, RentalStatus } from '../model/rental.types'

export const fetchMyRentals = async (
  api: ApiClient,
  status?: RentalStatus,
): Promise<RentalPage> =>
  unwrap(await api.GET('/api/v1/me/rentals', { params: { query: status ? { status } : {} } }))

export const createRentalRequest = async (
  api: ApiClient,
  payload: CreateRentalRequest,
  idempotencyKey: string,
): Promise<Rental> =>
  unwrap(
    await api.POST('/api/v1/rentals', {
      body: payload,
      params: { header: { 'Idempotency-Key': idempotencyKey } },
    }),
  )

export const cancelRentalRequest = async (api: ApiClient, id: string): Promise<Rental> =>
  unwrap(await api.POST('/api/v1/me/rentals/{id}/cancel', { params: { path: { id } } }))
