import type { components } from '~/shared/api/schema'

export type AnalyticsSummary = components['schemas']['AnalyticsSummary']
export type AnalyticsBucket = components['schemas']['AnalyticsBucket']
export type AnalyticsRevenue = components['schemas']['AnalyticsRevenue']
export type AnalyticsLotDetail = components['schemas']['AnalyticsLotDetail']
export type AnalyticsRental = components['schemas']['AnalyticsRental']
export type AnalyticsGroupBy = AnalyticsRevenue['group_by']
