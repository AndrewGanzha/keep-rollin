import { dayKeyOf, dayKeyToDate, zonedParts } from '../../../shared/lib/calendar'

export const DAY_MS = 24 * 60 * 60 * 1000

export const analyticsDayStart = (day: string, timeZone?: string): number => {
  const midnight = dayKeyToDate(day).getTime()
  const keyAt = (time: number) => dayKeyOf(new Date(time), timeZone).padStart(10, '0')
  const candidates = [midnight - DAY_MS, midnight, midnight + DAY_MS].map((time) => {
    const localDay = dayKeyToDate(keyAt(time))
    const { hour, minute } = zonedParts(new Date(time), timeZone)
    const localTime = localDay.setUTCHours(hour, minute)
    return midnight + time - localTime
  })

  // Choose the first midnight when the clock repeats it.
  const exact = candidates.filter(Number.isFinite).sort((left, right) => left - right)
    .find(time => keyAt(time) === day && keyAt(time - 1) < day)
  if (exact !== undefined) return exact

  // The clock may skip midnight. Find the first instant whose local date reaches this day.
  let before = midnight - DAY_MS
  let after = midnight + DAY_MS
  while (after - before > 1) {
    const middle = before + Math.floor((after - before) / 2)
    if (keyAt(middle) < day) before = middle
    else after = middle
  }
  return after
}
