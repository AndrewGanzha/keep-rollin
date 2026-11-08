export {
  fetchAnalyticsLot,
  fetchAnalyticsRevenue,
  fetchAnalyticsSummary,
} from './api/analytics.api'
export type {
  AnalyticsBucket,
  AnalyticsGroupBy,
  AnalyticsLotDetail,
  AnalyticsRental,
  AnalyticsRevenue,
  AnalyticsSummary,
} from './model/analytics.types'
export { default as RevenueBars } from './ui/RevenueBars.vue'
