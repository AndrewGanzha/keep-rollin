import { addDays, dayKeyOf, dayKeyToDate } from '~/shared/lib/calendar'
import { analyticsDayStart, DAY_MS } from './analytics-day'

export type PeriodPreset = 'week' | 'month' | 'quarter' | 'year' | 'custom'
export type DateSelection = (Date | null)[] | null

export interface AnalyticsDays {
  first: string
  last: string
}

const MAX_DURATION = 366 * DAY_MS

export const presetDays = (preset: Exclude<PeriodPreset, 'custom'>, today: string): AnalyticsDays => {
  const first = {
    week: () => addDays(today, -6),
    month: () => `${today.slice(0, 7)}-01`,
    quarter: () => addDays(today, -89),
    year: () => addDays(today, -364),
  }[preset]()

  return { first, last: today }
}

const isDayKey = (value: unknown): value is string => {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)
    || value < '0001-01-01' || value >= '9999-12-31') {
    return false
  }

  const date = dayKeyToDate(value)
  return Number.isFinite(date.getTime()) && date.toISOString().startsWith(value)
}

export const toAnalyticsRange = ({ first, last }: AnalyticsDays, timeZone?: string) => ({
  from: new Date(analyticsDayStart(first, timeZone)).toISOString(),
  to: new Date(analyticsDayStart(addDays(last, 1), timeZone)).toISOString(),
})

export const parseAnalyticsDays = (first: unknown, last: unknown, timeZone?: string): AnalyticsDays | null => {
  if (!isDayKey(first) || !isDayKey(last) || first > last) {
    return null
  }

  const { from, to } = toAnalyticsRange({ first, last }, timeZone)
  const duration = Date.parse(to) - Date.parse(from)

  return duration > 0 && duration <= MAX_DURATION && from >= '0001-01-01'
    ? { first, last }
    : null
}

export const selectedDays = (selection: DateSelection): AnalyticsDays | null => {
  const [first, last] = selection ?? []
  if (!first || !last || !Number.isFinite(first.getTime()) || !Number.isFinite(last.getTime())) {
    return null
  }

  // PrimeVue gives browser-local calendar dates. Convert those dates to tenant instants later.
  return {
    first: dayKeyOf(first).padStart(10, '0'),
    last: dayKeyOf(last).padStart(10, '0'),
  }
}

export const pickerDates = ({ first, last }: AnalyticsDays): DateSelection => [
  new Date(`${first}T00:00:00`),
  new Date(`${last}T00:00:00`),
]
