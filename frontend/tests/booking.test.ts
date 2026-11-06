import { describe, expect, it } from 'vitest'
import type { Lot } from '../app/entities/lot'
import {
  addUnits,
  durationOptions,
  estimatePrice,
  unitOf,
} from '../app/features/booking/create/model/booking'

const lot = { price_minor: 120000 } as Lot

describe('booking units', () => {
  it('treats daily and custom lots as day rentals', () => {
    expect(unitOf('daily')).toBe('day')
    expect(unitOf('custom')).toBe('day')
    expect(unitOf('hourly')).toBe('hour')
  })

  it('offers a day by default and a month for day rentals', () => {
    const options = durationOptions('day')

    expect(options[0]).toEqual({ label: '1 день', value: 1 })
    expect(options.map(option => option.value)).toContain(30)
  })

  it('keeps hourly options for hourly lots but includes a full day', () => {
    const values = durationOptions('hour').map(option => option.value)

    expect(values).toContain(1)
    expect(values).toContain(24)
  })

  it('adds days and hours', () => {
    const start = new Date('2026-11-06T10:00:00.000Z')

    expect(addUnits(start, 1, 'day').toISOString()).toBe('2026-11-07T10:00:00.000Z')
    expect(addUnits(start, 2, 'hour').toISOString()).toBe('2026-11-06T12:00:00.000Z')
  })

  it('estimates the price by the number of units', () => {
    expect(estimatePrice(lot, 7)).toBe(840000)
  })
})
