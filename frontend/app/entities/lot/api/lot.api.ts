import { unwrap, type ApiClient } from '~/shared/api'
import type { Availability, Lot, LotPage } from '../model/lot.types'

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
