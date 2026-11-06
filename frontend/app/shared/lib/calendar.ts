export type CalendarView = 'day' | 'week' | 'month'

export interface ZonedParts {
  year: number
  month: number
  day: number
  hour: number
  minute: number
  minutesOfDay: number
}

export interface CalendarRange {
  days: string[]
  from: string
  to: string
}

const pad = (value: number): string => String(value).padStart(2, '0')

const partsFormatters = new Map<string, Intl.DateTimeFormat>()

/** Календарные компоненты момента в таймзоне тенанта. */
export const zonedParts = (date: Date, timeZone?: string): ZonedParts => {
  const key = timeZone ?? 'default'
  let formatter = partsFormatters.get(key)

  if (!formatter) {
    formatter = new Intl.DateTimeFormat('en-CA', {
      timeZone,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hourCycle: 'h23',
    })
    partsFormatters.set(key, formatter)
  }

  const parts = formatter.formatToParts(date)
  const read = (type: Intl.DateTimeFormatPartTypes): number =>
    Number(parts.find(part => part.type === type)?.value ?? 0)
  const hour = read('hour')
  const minute = read('minute')

  return {
    year: read('year'),
    month: read('month'),
    day: read('day'),
    hour,
    minute,
    minutesOfDay: hour * 60 + minute,
  }
}

/** Ключ дня `YYYY-MM-DD` в таймзоне тенанта. */
export const dayKeyOf = (date: Date, timeZone?: string): string => {
  const { year, month, day } = zonedParts(date, timeZone)

  return `${year}-${pad(month)}-${pad(day)}`
}

export const dayKeyToDate = (dayKey: string): Date => new Date(`${dayKey}T00:00:00.000Z`)

export const addDays = (dayKey: string, amount: number): string => {
  const date = dayKeyToDate(dayKey)
  date.setUTCDate(date.getUTCDate() + amount)

  return date.toISOString().slice(0, 10)
}

/** Понедельник недели, содержащей день. */
export const startOfWeek = (dayKey: string): string => {
  const weekday = dayKeyToDate(dayKey).getUTCDay()

  return addDays(dayKey, -((weekday + 6) % 7))
}

export const shiftMonth = (dayKey: string, amount: number): string => {
  const date = dayKeyToDate(dayKey)

  return new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + amount, 1))
    .toISOString()
    .slice(0, 10)
}

/** 42 дня сетки месяца, начиная с понедельника. */
export const monthGrid = (dayKey: string): string[] => {
  const date = dayKeyToDate(dayKey)
  const first = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), 1))
    .toISOString()
    .slice(0, 10)
  const start = startOfWeek(first)

  return Array.from({ length: 42 }, (_, index) => addDays(start, index))
}

/** UTC-инстант полуночи дня в таймзоне тенанта. */
export const zonedDayStartIso = (dayKey: string, timeZone?: string): string => {
  const [year, month, day] = dayKey.split('-').map(Number)
  const target = Date.UTC(year!, month! - 1, day!)
  let instant = target

  for (let pass = 0; pass < 2; pass += 1) {
    const parts = zonedParts(new Date(instant), timeZone)
    const wallClock = Date.UTC(parts.year, parts.month - 1, parts.day, parts.hour, parts.minute)
    instant = target - (wallClock - instant)
  }

  return new Date(instant).toISOString()
}

export const daysForView = (view: CalendarView, anchor: string): string[] => {
  if (view === 'day') {
    return [anchor]
  }

  if (view === 'week') {
    const start = startOfWeek(anchor)

    return Array.from({ length: 7 }, (_, index) => addDays(start, index))
  }

  return monthGrid(anchor)
}

export const calendarRange = (
  view: CalendarView,
  anchor: string,
  timeZone?: string,
): CalendarRange => {
  const days = daysForView(view, anchor)

  return {
    days,
    from: zonedDayStartIso(days[0]!, timeZone),
    to: zonedDayStartIso(addDays(days[days.length - 1]!, 1), timeZone),
  }
}
