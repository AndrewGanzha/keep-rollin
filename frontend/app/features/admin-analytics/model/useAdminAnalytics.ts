import {
  fetchAnalyticsLot,
  fetchAnalyticsRevenue,
  fetchAnalyticsSummary,
  type AnalyticsBucket,
  type AnalyticsLotDetail,
} from '~/entities/analytics'
import { useTenant } from '~/entities/tenant'
import { ApiError, useApi } from '~/shared/api'
import { addDays, dayKeyOf, dayKeyToDate, zonedDayStartIso } from '~/shared/lib'

export type PeriodPreset = 'week' | 'month' | 'quarter' | 'year' | 'custom'

export const periodPresets: { label: string; value: PeriodPreset }[] = [
  { label: 'Неделя', value: 'week' },
  { label: 'Месяц', value: 'month' },
  { label: 'Квартал', value: 'quarter' },
  { label: 'Год', value: 'year' },
  { label: 'Свой', value: 'custom' },
]

export const useAdminAnalytics = async () => {
  const api = useApi()
  const toast = useToast()
  const tenant = useTenant()

  const timeZone = computed(() => tenant.value?.timezone)
  const todayKey = computed(() => dayKeyOf(new Date(), timeZone.value))

  const preset = ref<PeriodPreset>('month')
  const customRange = ref<Date[] | null>(null)

  const bounds = computed(() => {
    const today = todayKey.value

    if (preset.value === 'week') {
      return { start: addDays(today, -6), end: addDays(today, 1) }
    }

    if (preset.value === 'quarter') {
      return { start: addDays(today, -89), end: addDays(today, 1) }
    }

    if (preset.value === 'year') {
      return { start: addDays(today, -364), end: addDays(today, 1) }
    }

    if (preset.value === 'custom' && customRange.value?.length === 2) {
      const [start, end] = customRange.value

      return {
        start: dayKeyOf(start!, timeZone.value),
        end: addDays(dayKeyOf(end!, timeZone.value), 1),
      }
    }

    return { start: `${today.slice(0, 7)}-01`, end: addDays(today, 1) }
  })

  const range = computed(() => ({
    from: zonedDayStartIso(bounds.value.start, timeZone.value),
    to: zonedDayStartIso(bounds.value.end, timeZone.value),
  }))

  const periodFormatter = new Intl.DateTimeFormat('ru-RU', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  })

  const periodLabel = computed(() =>
    `${periodFormatter.format(dayKeyToDate(bounds.value.start))} — ${periodFormatter.format(dayKeyToDate(addDays(bounds.value.end, -1)))}`,
  )

  watch(preset, (value) => {
    if (value === 'custom' && !customRange.value) {
      customRange.value = [
        dayKeyToDate(addDays(todayKey.value, -29)),
        dayKeyToDate(todayKey.value),
      ]
    }
  })

  const request = useAsyncData(
    'admin-analytics',
    async () => {
      const [summary, day, lots, categories] = await Promise.all([
        fetchAnalyticsSummary(api, range.value.from, range.value.to),
        fetchAnalyticsRevenue(api, 'day', range.value.from, range.value.to),
        fetchAnalyticsRevenue(api, 'lot', range.value.from, range.value.to),
        fetchAnalyticsRevenue(api, 'category', range.value.from, range.value.to),
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
  await request

  const detail = ref<AnalyticsLotDetail | null>(null)
  const detailLoading = ref(false)

  const openLot = async (bucket: AnalyticsBucket) => {
    detailLoading.value = true

    try {
      detail.value = await fetchAnalyticsLot(api, bucket.key, range.value.from, range.value.to)
    } catch (caught) {
      const message = caught instanceof ApiError ? caught.message : 'Не удалось загрузить лот'
      toast.add({ severity: 'error', summary: message, life: 4000 })
    } finally {
      detailLoading.value = false
    }
  }

  const closeDetail = () => {
    detail.value = null
  }

  return {
    data: request.data,
    pending: request.pending,
    error: request.error,
    refresh: request.refresh,
    preset,
    customRange,
    periodLabel,
    openLot,
    detail,
    detailLoading,
    closeDetail,
  }
}
