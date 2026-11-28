import type { components, paths } from '~/shared/api/schema'

export type AnalyticsSummary = components['schemas']['AnalyticsSummary']
export type AnalyticsBucket = components['schemas']['AnalyticsBucket']
export type AnalyticsRevenue = components['schemas']['AnalyticsRevenue']
export type AnalyticsLotDetail = components['schemas']['AnalyticsLotDetail']
export type AnalyticsRental = components['schemas']['AnalyticsRental']
export type AnalyticsGroupBy = AnalyticsRevenue['group_by']
export type AnalyticsRange = paths['/api/v1/admin/analytics/summary']['get']['parameters']['query']
export type AnalyticsComparison = paths['/api/v1/admin/analytics/compare']['get']['responses'][200]['content']['application/json']
