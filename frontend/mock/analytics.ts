import type { components } from '../app/shared/api/schema'
import { analyticsDayStart, DAY_MS } from '../app/features/admin-analytics/model/analytics-day'
import { addDays, dayKeyOf } from '../app/shared/lib/calendar'

type Lot = Pick<components['schemas']['Lot'], 'id' | 'name' | 'category_id' | 'status'>
type Category = components['schemas']['Category']
type Rental = components['schemas']['Rental']
type Summary = components['schemas']['AnalyticsSummary']
type Revenue = components['schemas']['AnalyticsRevenue']
type Comparison = components['schemas']['AnalyticsComparison']

interface Period {
  fromMs: number
  toMs: number
}

const billed = (rental: Rental) => ['active', 'overdue', 'completed'].includes(rental.status)

const time = (value: unknown): number =>
  typeof value === 'string' && /(?:Z|[+-]\d{2}:\d{2})$/i.test(value) ? Date.parse(value) : Number.NaN

export const parseAnalyticsRange = (from: unknown, to: unknown): Period | null => {
  const fromMs = time(from)
  const toMs = time(to)
  const duration = toMs - fromMs

  return duration > 0 && duration <= 366 * DAY_MS ? { fromMs, toMs } : null
}

const occupiedByLot = (rentals: Rental[], lotId: string, { fromMs, toMs }: Period): number => {
  const intervals = rentals
    .filter(rental => rental.lot.id === lotId && billed(rental))
    .map(rental => [Math.max(Date.parse(rental.start_time), fromMs), Math.min(Date.parse(rental.end_time), toMs)] as const)
    .filter(([start, end]) => start < end)
    .sort(([left], [right]) => left - right)

  let occupied = 0
  let lastEnd = fromMs
  for (const [start, end] of intervals) {
    occupied += Math.max(0, end - Math.max(start, lastEnd))
    lastEnd = Math.max(lastEnd, end)
  }
  return occupied
}

const csvField = (value: string | number): string => {
  let text = String(value)
  const leading = text.normalize('NFKC').trimStart().replace(/^[\ufeff\u200b\u200c\u200d]+/, '').trimStart()
  if (typeof value === 'string' && (/^[\t\r\n]/.test(text) || /^[=+@-]/.test(leading))) {
    text = `'${text}`
  }
  return /[;"\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text
}

export const createMockAnalytics = (lots: Lot[], categories: Category[], rentals: Rental[], timeZone: string) => {
  const inPeriod = ({ fromMs, toMs }: Period, lotId?: string): Rental[] =>
    rentals.filter(rental =>
      Date.parse(rental.start_time) >= fromMs
      && Date.parse(rental.start_time) < toMs
      && (!lotId || rental.lot.id === lotId),
    )

  const summary = (period: Period, scope = lots): Summary => {
    const ids = new Set(scope.map(lot => lot.id))
    const scoped = inPeriod(period).filter(rental => ids.has(rental.lot.id))
    const revenue = scoped.filter(billed).reduce((sum, rental) => sum + rental.price_minor, 0)
    const cancelled = scoped.filter(rental => rental.status === 'cancelled').length
    const countWithoutCancelled = scoped.length - cancelled
    const activeLots = scope.filter(lot => lot.status !== 'archived')
    const available = activeLots.length * (period.toMs - period.fromMs)
    const occupied = activeLots.reduce((sum, lot) => sum + occupiedByLot(rentals, lot.id, period), 0)

    return {
      from: new Date(period.fromMs).toISOString(),
      to: new Date(period.toMs).toISOString(),
      revenue_minor: revenue,
      rentals_count: scoped.length,
      cancelled_count: cancelled,
      overdue_count: scoped.filter(rental => rental.status === 'overdue').length,
      avg_rental_minor: countWithoutCancelled > 0 ? Math.round(revenue / countWithoutCancelled) : 0,
      utilization_pct: available > 0 ? Math.round(occupied * 1000 / available) / 10 : 0,
    }
  }

  const bucket = (key: string, label: string, period: Period, scope: Lot[]) => {
    const { rentals_count, cancelled_count, revenue_minor, utilization_pct } = summary(period, scope)
    return { key, label, rentals_count, cancelled_count, revenue_minor, utilization_pct }
  }

  const byRevenue = (left: Revenue['buckets'][number], right: Revenue['buckets'][number]) =>
    right.revenue_minor - left.revenue_minor || left.label.localeCompare(right.label, 'ru')

  const buckets = (group: Revenue['group_by'], period: Period, scope = lots): Revenue['buckets'] => {
    if (group === 'lot') {
      return scope.map(lot => bucket(lot.id, lot.name, period, [lot])).sort(byRevenue)
    }
    if (group === 'category') {
      return categories
        .map(category => bucket(category.id, category.name, period, scope.filter(lot => lot.category_id === category.id)))
        .sort(byRevenue)
    }

    const items: Revenue['buckets'] = []
    let start = period.fromMs
    while (start < period.toMs) {
      const key = dayKeyOf(new Date(start), timeZone).padStart(10, '0')
      const end = Math.min(analyticsDayStart(addDays(key, 1), timeZone), period.toMs)
      items.push(bucket(key, key, { fromMs: start, toMs: end }, scope))
      start = end
    }
    return items
  }

  const compare = (period: Period, baseline: Period): Comparison => {
    const current = summary(period)
    const previous = summary(baseline)
    return {
      current,
      previous,
      delta: {
        revenue_minor: current.revenue_minor - previous.revenue_minor,
        rentals_count: current.rentals_count - previous.rentals_count,
        cancelled_count: current.cancelled_count - previous.cancelled_count,
        overdue_count: current.overdue_count - previous.overdue_count,
        avg_rental_minor: current.avg_rental_minor - previous.avg_rental_minor,
        utilization_pct: Number((current.utilization_pct - previous.utilization_pct).toFixed(1)),
      },
    }
  }

  const csv = (period: Period) => {
    const headers = 'ID аренды;Лот;Категория;Начало;Окончание;Статус;Сумма в минорных единицах;Валюта'
    const lines = inPeriod(period)
      .sort((left, right) => left.start_time.localeCompare(right.start_time) || left.id.localeCompare(right.id))
      .map((rental) => {
        const lot = lots.find(item => item.id === rental.lot.id)
        const category = categories.find(item => item.id === lot?.category_id)
        return [
          rental.id, lot?.name ?? rental.lot.name, category?.name ?? '', rental.start_time,
          rental.end_time, rental.status, rental.price_minor, rental.currency,
        ].map(csvField).join(';')
      })
    return `\ufeff${[headers, ...lines].join('\r\n')}\r\n`
  }

  return { inPeriod, summary, buckets, compare, csv }
}
