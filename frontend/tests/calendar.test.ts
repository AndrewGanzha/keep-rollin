import { describe, expect, it } from 'vitest'
import {
  addDays,
  calendarRange,
  dayKeyOf,
  monthGrid,
  shiftMonth,
  startOfWeek,
  zonedDayStartIso,
} from '../app/shared/lib/calendar'

describe('calendar helpers', () => {
  it('builds day keys in the tenant timezone', () => {
    expect(dayKeyOf(new Date('2026-11-05T22:30:00Z'), 'Europe/Moscow')).toBe('2026-11-06')
    expect(dayKeyOf(new Date('2026-11-05T20:30:00Z'), 'Europe/Moscow')).toBe('2026-11-05')
  })

  it('starts weeks on Monday', () => {
    expect(startOfWeek('2026-11-08')).toBe('2026-11-02')
    expect(startOfWeek('2026-11-02')).toBe('2026-11-02')
  })

  it('adds days across month boundaries', () => {
    expect(addDays('2026-10-31', 1)).toBe('2026-11-01')
    expect(addDays('2026-11-01', -1)).toBe('2026-10-31')
  })

  it('builds a six-week month grid', () => {
    const grid = monthGrid('2026-11-06')

    expect(grid).toHaveLength(42)
    expect(grid[0]).toBe('2026-10-26')
    expect(grid[41]).toBe('2026-12-06')
  })

  it('shifts months from any day of the month', () => {
    expect(shiftMonth('2026-01-31', 1)).toBe('2026-02-01')
    expect(shiftMonth('2026-01-15', -1)).toBe('2025-12-01')
  })

  it('converts tenant midnight to UTC', () => {
    expect(zonedDayStartIso('2026-11-06', 'Europe/Moscow')).toBe('2026-11-05T21:00:00.000Z')
  })

  it('covers the whole month range including adjacent grid days', () => {
    const range = calendarRange('month', '2026-11-06', 'Europe/Moscow')

    expect(range.days).toHaveLength(42)
    expect(range.from).toBe('2026-10-25T21:00:00.000Z')
    expect(range.to).toBe('2026-12-06T21:00:00.000Z')
  })
})
