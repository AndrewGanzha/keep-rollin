import { unwrap, type ApiClient } from '~/shared/api'
import type {
  AnalyticsGroupBy,
  AnalyticsLotDetail,
  AnalyticsRevenue,
  AnalyticsSummary,
} from '../model/analytics.types'

export const fetchAnalyticsSummary = async (
  api: ApiClient,
  from: string,
  to: string,
): Promise<AnalyticsSummary> =>
  unwrap(await api.GET('/api/v1/admin/analytics/summary', { params: { query: { from, to } } }))

export const fetchAnalyticsRevenue = async (
  api: ApiClient,
  groupBy: AnalyticsGroupBy,
  from: string,
  to: string,
): Promise<AnalyticsRevenue> =>
  unwrap(
    await api.GET('/api/v1/admin/analytics/revenue', {
      params: { query: { group_by: groupBy, from, to } },
    }),
  )

export const fetchAnalyticsLot = async (
  api: ApiClient,
  lotId: string,
  from: string,
  to: string,
): Promise<AnalyticsLotDetail> =>
  unwrap(
    await api.GET('/api/v1/admin/analytics/lots/{lot_id}', {
      params: { path: { lot_id: lotId }, query: { from, to } },
    }),
  )
