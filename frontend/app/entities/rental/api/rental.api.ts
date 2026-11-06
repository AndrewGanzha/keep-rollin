import { unwrap, type ApiClient } from '~/shared/api'
import type {
  AdminRental,
  AdminRentalPage,
  AdminRentalStatus,
  CancelAdminRentalRequest,
  CloseRentalRequest,
  CreateRentalRequest,
  Rental,
  RentalPage,
  RentalStatus,
} from '../model/rental.types'

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

export interface AdminRentalQuery {
  status?: AdminRentalStatus
  lot_id?: string
  from?: string
  to?: string
  limit?: number
  offset?: number
}

export const fetchAdminRentals = async (
  api: ApiClient,
  query: AdminRentalQuery = {},
): Promise<AdminRentalPage> =>
  unwrap(await api.GET('/api/v1/admin/rentals', { params: { query } }))

export const closeAdminRental = async (
  api: ApiClient,
  id: string,
  payload: CloseRentalRequest,
): Promise<AdminRental> =>
  unwrap(
    await api.POST('/api/v1/admin/rentals/{id}/close', {
      params: { path: { id } },
      body: payload,
    }),
  )

export const cancelAdminRental = async (
  api: ApiClient,
  id: string,
  payload: CancelAdminRentalRequest,
): Promise<AdminRental> =>
  unwrap(
    await api.POST('/api/v1/admin/rentals/{id}/cancel', {
      params: { path: { id } },
      body: payload,
    }),
  )
