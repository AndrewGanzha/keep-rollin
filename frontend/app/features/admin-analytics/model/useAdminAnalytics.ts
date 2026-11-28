import {
  fetchAnalyticsComparison,
  fetchAnalyticsCsv,
  fetchAnalyticsLot,
  fetchAnalyticsRevenue,
  fetchAnalyticsSummary,
  fetchAnalyticsUtilization,
  type AnalyticsBucket,
  type AnalyticsLotDetail,
} from '~/entities/analytics'
import { useTenant } from '~/entities/tenant'
import { ApiError, useApi } from '~/shared/api'
import { dayKeyOf, dayKeyToDate } from '~/shared/lib'
import {
  parseAnalyticsDays,
  pickerDates,
  presetDays,
  selectedDays,
  toAnalyticsRange,
  type AnalyticsDays,
  type DateSelection,
  type PeriodPreset,
} from './analytics-period'

export const periodPresets: { label: string; value: PeriodPreset }[] = [
  { label: 'Неделя', value: 'week' },
  { label: 'Месяц', value: 'month' },
  { label: 'Квартал', value: 'quarter' },
  { label: 'Год', value: 'year' },
  { label: 'Свой', value: 'custom' },
]

const periodFormatter = new Intl.DateTimeFormat('ru-RU', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  timeZone: 'UTC',
})
const formatPeriod = ({ first, last }: AnalyticsDays) =>
  `${periodFormatter.format(dayKeyToDate(first))} — ${periodFormatter.format(dayKeyToDate(last))}`

export const useAdminAnalytics = async () => {
  const api = useApi()
  const toast = useToast()
  const tenant = useTenant()
  const route = useRoute()
  const router = useRouter()

  const timeZone = computed(() => tenant.value?.timezone)
  const currency = computed(() => tenant.value?.currency)
  const todayKey = computed(() => dayKeyOf(new Date(), timeZone.value))
  const initialPeriod = parseAnalyticsDays(route.query.from, route.query.to, timeZone.value)
  const preset = ref<PeriodPreset>(initialPeriod ? 'custom' : 'month')
  const customRange = ref<DateSelection>(initialPeriod ? pickerDates(initialPeriod) : null)
  const comparisonRange = ref<DateSelection>(null)

  const parseSelection = (selection: DateSelection) => {
    const days = selectedDays(selection)
    return days ? parseAnalyticsDays(days.first, days.last, timeZone.value) : null
  }
  const customDays = computed(() => parseSelection(customRange.value))
  const comparisonDays = computed(() => parseSelection(comparisonRange.value))
  const periodReady = computed(() => preset.value !== 'custom' || customDays.value !== null)
  const periodError = computed(() =>
    preset.value === 'custom' && selectedDays(customRange.value) !== null && !customDays.value,
  )
  const comparisonPeriodError = computed(() =>
    selectedDays(comparisonRange.value) !== null && !comparisonDays.value,
  )
  const period = computed<AnalyticsDays>((previous) => {
    if (preset.value !== 'custom') return presetDays(preset.value, todayKey.value)
    return customDays.value ?? previous ?? presetDays('month', todayKey.value)
  })
  const range = computed(() => toAnalyticsRange(period.value, timeZone.value))
  const comparisonQuery = computed(() =>
    comparisonDays.value ? toAnalyticsRange(comparisonDays.value, timeZone.value) : null,
  )
  const periodLabel = computed(() => formatPeriod(period.value))
  const comparisonLabel = computed(() => comparisonDays.value ? formatPeriod(comparisonDays.value) : '')

  watch(preset, (value) => {
    if (value === 'custom' && !customRange.value) {
      customRange.value = pickerDates(period.value)
    }
  })
  watch(period, ({ first, last }) => {
    if (route.query.from !== first || route.query.to !== last) {
      void router.replace({ query: { ...route.query, from: first, to: last } })
    }
  })

  const request = useAsyncData(
    'admin-analytics',
    async (_nuxtApp, { signal }) => {
      const query = range.value
      const [summary, day, lots, categories] = await Promise.all([
        fetchAnalyticsSummary(api, query, signal),
        fetchAnalyticsRevenue(api, 'day', query, signal),
        fetchAnalyticsUtilization(api, query, signal),
        fetchAnalyticsRevenue(api, 'category', query, signal),
      ])

      return {
        summary,
        day: day.buckets,
        lots: lots.buckets,
        categories: categories.buckets,
      }
    },
    { watch: [range] },
  )
  const comparisonRequest = useAsyncData(
    'admin-analytics-compare',
    async (_nuxtApp, { signal }) => {
      const previous = comparisonQuery.value
      return { comparison: previous ? await fetchAnalyticsComparison(api, range.value, previous, signal) : null }
    },
    { watch: [range, comparisonQuery] },
  )

  const detail = ref<AnalyticsLotDetail | null>(null)
  const detailLoading = ref(false)
  const detailOffset = ref(0)
  const detailPageSize = 100
  let detailRequest: AbortController | undefined

  const closeDetail = () => {
    detailRequest?.abort()
    detail.value = null
    detailLoading.value = false
  }
  watch(range, closeDetail)
  onScopeDispose(() => detailRequest?.abort())

  const loadLot = async (lotId: string, offset: number) => {
    detailRequest?.abort()
    const controller = new AbortController()
    detailRequest = controller
    detailLoading.value = true
    const previousOffset = detailOffset.value
    detailOffset.value = offset

    try {
      const next = await fetchAnalyticsLot(api, lotId, range.value, { offset, limit: detailPageSize }, controller.signal)
      if (!controller.signal.aborted) {
        detail.value = next
      }
    } catch (caught) {
      if (!controller.signal.aborted) {
        detailOffset.value = previousOffset
        const message = caught instanceof ApiError ? caught.message : 'Не удалось загрузить лот'
        toast.add({ severity: 'error', summary: message, life: 4000 })
      }
    } finally {
      if (detailRequest === controller) detailLoading.value = false
    }
  }

  const openLot = (bucket: AnalyticsBucket) => loadLot(bucket.key, 0)
  const pageDetail = (offset: number) => detail.value && loadLot(detail.value.lot.id, offset)

  const exporting = ref(false)
  const downloadCsv = async () => {
    if (!periodReady.value || exporting.value) return

    exporting.value = true
    const { first, last } = period.value
    const fallback = `${tenant.value?.slug ?? 'keep-rollin'}_rentals_${first}_${last}.csv`
    try {
      const { blob, filename } = await fetchAnalyticsCsv(api, range.value, fallback)
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = filename
      document.body.append(link)
      link.click()
      link.remove()
      window.setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (caught) {
      const message = caught instanceof ApiError ? caught.message : 'Не удалось скачать CSV'
      toast.add({ severity: 'error', summary: message, life: 4000 })
    } finally {
      exporting.value = false
    }
  }

  await Promise.all([request, comparisonRequest])

  return {
    data: request.data,
    pending: request.pending,
    error: request.error,
    refresh: request.refresh,
    preset,
    customRange,
    periodLabel,
    periodReady,
    periodError,
    currency,
    comparisonRange,
    comparisonLabel,
    comparisonPeriodError,
    comparison: computed(() => comparisonQuery.value ? comparisonRequest.data.value?.comparison : null),
    comparisonPending: comparisonRequest.pending,
    comparisonError: comparisonRequest.error,
    refreshComparison: comparisonRequest.refresh,
    openLot,
    detail,
    detailLoading,
    detailOffset,
    detailPageSize,
    pageDetail,
    closeDetail,
    downloadCsv,
    exporting,
  }
}
