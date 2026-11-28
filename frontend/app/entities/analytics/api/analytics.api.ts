import { unwrap, type ApiClient } from '~/shared/api'
import type {
  AnalyticsComparison,
  AnalyticsGroupBy,
  AnalyticsLotDetail,
  AnalyticsRange,
  AnalyticsRevenue,
  AnalyticsSummary,
} from '../model/analytics.types'

export const fetchAnalyticsSummary = async (
  api: ApiClient,
  query: AnalyticsRange,
  signal?: AbortSignal,
): Promise<AnalyticsSummary> =>
  unwrap(await api.GET('/api/v1/admin/analytics/summary', { params: { query }, signal }))

export const fetchAnalyticsRevenue = async (
  api: ApiClient,
  groupBy: AnalyticsGroupBy,
  range: AnalyticsRange,
  signal?: AbortSignal,
): Promise<AnalyticsRevenue> =>
  unwrap(
    await api.GET('/api/v1/admin/analytics/revenue', {
      params: { query: { ...range, group_by: groupBy } },
      signal,
    }),
  )

export const fetchAnalyticsUtilization = async (
  api: ApiClient,
  query: AnalyticsRange,
  signal?: AbortSignal,
): Promise<AnalyticsRevenue> =>
  unwrap(await api.GET('/api/v1/admin/analytics/utilization', { params: { query }, signal }))

export const fetchAnalyticsComparison = async (
  api: ApiClient,
  current: AnalyticsRange,
  previous: AnalyticsRange,
  signal?: AbortSignal,
): Promise<AnalyticsComparison> =>
  unwrap(
    await api.GET('/api/v1/admin/analytics/compare', {
      params: { query: { ...current, compare_from: previous.from, compare_to: previous.to } },
      signal,
    }),
  )

export const fetchAnalyticsLot = async (
  api: ApiClient,
  lotId: string,
  range: AnalyticsRange,
  page: { offset: number; limit: number },
  signal?: AbortSignal,
): Promise<AnalyticsLotDetail> =>
  unwrap(
    await api.GET('/api/v1/admin/analytics/lots/{lot_id}', {
      params: { path: { lot_id: lotId }, query: { ...range, ...page } },
      signal,
    }),
  )

const csvFilename = (disposition: string | null, fallback: string): string => {
  const encoded = disposition?.match(/(?:^|;)\s*filename\*=UTF-8''([^;]+)/i)?.[1]
  if (encoded) {
    try {
      return decodeURIComponent(encoded.trim())
    } catch {
      // Older servers may also send an ASCII filename.
    }
  }

  const plain = disposition?.match(/(?:^|;)\s*filename=(?:"([^"]+)"|([^;]+))/i)
  return (plain?.[1] ?? plain?.[2])?.trim() || fallback
}

export const fetchAnalyticsCsv = async (api: ApiClient, range: AnalyticsRange, fallbackName: string) => {
  const result = await api.GET('/api/v1/admin/analytics/export', {
    params: { query: { ...range, report: 'rentals', format: 'csv' } },
    parseAs: 'blob',
  })

  return {
    blob: unwrap(result),
    filename: csvFilename(result.response.headers.get('content-disposition'), fallbackName),
  }
}
