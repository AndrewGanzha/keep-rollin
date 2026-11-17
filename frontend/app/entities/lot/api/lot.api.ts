import { unwrap, type ApiClient } from '~/shared/api'
import type {
  Availability,
  CreateLotRequest,
  Lot,
  LotPage,
  LotStatus,
  LotStatusRequest,
  Quote,
  UpdateLotRequest,
} from '../model/lot.types'

export interface LotListQuery {
  category_id?: string
  q?: string
  limit?: number
  offset?: number
}

export const fetchLots = async (api: ApiClient, query: LotListQuery): Promise<LotPage> =>
  unwrap(await api.GET('/api/v1/public/lots', { params: { query } }))

export const fetchLot = async (api: ApiClient, slug: string): Promise<Lot> =>
  unwrap(await api.GET('/api/v1/public/lots/{slug}', { params: { path: { slug } } }))

export const fetchAvailability = async (
  api: ApiClient,
  slug: string,
  from: string,
  to: string,
): Promise<Availability> =>
  unwrap(
    await api.GET('/api/v1/public/lots/{slug}/availability', {
      params: { path: { slug }, query: { from, to } },
    }),
  )

export const fetchQuote = async (
  api: ApiClient,
  slug: string,
  start: string,
  end: string,
  signal?: AbortSignal,
): Promise<Quote> =>
  unwrap(
    await api.GET('/api/v1/public/lots/{slug}/quote', {
      params: { path: { slug }, query: { start, end } },
      signal,
    }),
  )

export interface AdminLotQuery {
  category_id?: string
  status?: LotStatus
  q?: string
  limit?: number
  offset?: number
}

export const fetchAdminLots = async (
  api: ApiClient,
  query: AdminLotQuery = {},
): Promise<LotPage> =>
  unwrap(await api.GET('/api/v1/admin/lots', { params: { query } }))

export const createLot = async (
  api: ApiClient,
  payload: CreateLotRequest,
): Promise<Lot> =>
  unwrap(await api.POST('/api/v1/admin/lots', { body: payload }))

export const updateLot = async (
  api: ApiClient,
  id: string,
  payload: UpdateLotRequest,
): Promise<Lot> =>
  unwrap(
    await api.PATCH('/api/v1/admin/lots/{id}', {
      params: { path: { id } },
      body: payload,
    }),
  )

export const setLotStatus = async (
  api: ApiClient,
  id: string,
  payload: LotStatusRequest,
): Promise<Lot> =>
  unwrap(
    await api.POST('/api/v1/admin/lots/{id}/status', {
      params: { path: { id } },
      body: payload,
    }),
  )
