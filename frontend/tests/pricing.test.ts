import { describe, expect, it } from 'vitest'
import {
  computePrice,
  priceForRange,
  priceFromOf,
  validateAllowedDurations,
  validateVariants,
  PricingError,
  UNIT_MS,
  type PriceTier,
} from '../mock/pricing'

const tier = (minUnits: number, priceMinor: number): PriceTier => ({
  min_units: minUnits,
  price_per_unit_minor: priceMinor,
})

const ONE_BATTERY = [tier(1, 130000), tier(7, 40000), tier(30, 40000)]
const TWO_BATTERIES = [tier(1, 150000), tier(7, 50000), tier(30, 40000)]
const HOURS = [tier(1, 50000), tier(3, 40000), tier(24, 30000)]

const variant = (batteryCount: number, tiers: PriceTier[], isActive = true) => ({
  id: `variant-${batteryCount}`,
  battery_count: batteryCount,
  is_active: isActive,
  price_tiers: tiers,
})

describe('D-20: тир и round-up', () => {
  const vectors: [number, number, number][] = [
    [1, 130000, 150000],
    [2, 260000, 300000],
    [3, 280000, 350000],
    [4, 280000, 350000],
    [5, 280000, 350000],
    [6, 280000, 350000],
    [7, 280000, 350000],
    [8, 320000, 400000],
    [10, 400000, 500000],
    [29, 1160000, 1200000],
    [30, 1200000, 1200000],
    [31, 1240000, 1240000],
    [60, 2400000, 2400000],
  ]

  it.each(vectors)('%i суток: 1 АКБ = %i, 2 АКБ = %i', (units, one, two) => {
    expect(computePrice(ONE_BATTERY, units).totalMinor).toBe(one)
    expect(computePrice(TWO_BATTERIES, units).totalMinor).toBe(two)
  })

  it('reports the tier that won after round-up', () => {
    expect(computePrice(ONE_BATTERY, 3)).toEqual({ totalMinor: 280000, tierMinUnits: 7 })
    expect(computePrice(TWO_BATTERIES, 29)).toEqual({ totalMinor: 1200000, tierMinUnits: 30 })
    expect(computePrice(TWO_BATTERIES, 31)).toEqual({ totalMinor: 1240000, tierMinUnits: 30 })
  })

  it('never makes a longer rental cheaper than a shorter one', () => {
    for (let units = 2; units <= 60; units += 1) {
      expect(computePrice(ONE_BATTERY, units).totalMinor)
        .toBeGreaterThanOrEqual(computePrice(ONE_BATTERY, units - 1).totalMinor)
    }
  })

  it('supports hourly lots', () => {
    expect(computePrice(HOURS, 1).totalMinor).toBe(50000)
    expect(computePrice(HOURS, 23).totalMinor).toBe(720000)
    expect(computePrice(HOURS, 25).totalMinor).toBe(750000)
  })
})

describe('границы срока', () => {
  it('accepts the minimal allowed duration', () => {
    const result = priceForRange(ONE_BATTERY, [1, 3, 7, 30], 'day', 0, UNIT_MS.day)

    expect(result.units).toBe(1)
    expect(result.totalMinor).toBe(130000)
  })

  it('rejects a duration below the allowed minimum', () => {
    expect(() => priceForRange(ONE_BATTERY, [7, 30], 'day', 0, 6 * UNIT_MS.day))
      .toThrowError(PricingError)

    try {
      priceForRange(ONE_BATTERY, [7, 30], 'day', 0, 6 * UNIT_MS.day)
    } catch (caught) {
      expect((caught as PricingError).code).toBe('rental_period_not_allowed')
    }
  })

  it('rejects an empty or reversed interval', () => {
    expect(() => priceForRange(ONE_BATTERY, [1], 'day', 0, 0))
      .toThrowError(PricingError)
    expect(() => priceForRange(ONE_BATTERY, [1], 'day', UNIT_MS.day, 0))
      .toThrowError(PricingError)
  })

  it('rounds partial units up', () => {
    expect(priceForRange(ONE_BATTERY, [1], 'day', 0, 23 * 60 * 60 * 1000).units).toBe(1)
    expect(priceForRange(ONE_BATTERY, [1], 'day', 0, 25 * 60 * 60 * 1000).units).toBe(2)
  })
})

describe('D-22: price_from', () => {
  it('takes the minimum per-unit price and breaks ties by at_units', () => {
    expect(priceFromOf([variant(1, ONE_BATTERY), variant(2, TWO_BATTERIES)], 'day')).toEqual({
      amount_minor: 40000,
      per: 'day',
      at_units: 7,
      battery_count: 1,
    })
  })

  it('ignores inactive variants', () => {
    expect(priceFromOf([variant(1, ONE_BATTERY, false), variant(2, TWO_BATTERIES)], 'day')?.battery_count)
      .toBe(2)
  })

  it('returns null when there are no active variants', () => {
    expect(priceFromOf([variant(1, ONE_BATTERY, false)], 'day')).toBeNull()
  })
})

describe('валидация админ-формы', () => {
  it('accepts sorted unique durations', () => {
    expect(validateAllowedDurations([1, 3, 7, 30])).toBeNull()
  })

  it.each([
    [[7, 3], 'по возрастанию'],
    [[1, 1], 'повторяться'],
    [[0], 'целые числа'],
    [[366], 'целые числа'],
    [[], 'хотя бы один'],
  ])('rejects %j', (durations, message) => {
    expect(validateAllowedDurations(durations)).toContain(message)
  })

  it('rejects duplicate battery variants and a growing price', () => {
    const duplicate = validateVariants([
      { battery_count: 1, price_tiers: [tier(1, 100000)] },
      { battery_count: 1, price_tiers: [tier(1, 90000)] },
    ], [1], '48v')
    expect(duplicate['variants.1.battery_count']).toBeDefined()

    const growing = validateVariants([
      { battery_count: 1, price_tiers: [tier(1, 100000), tier(7, 120000)] },
    ], [1, 7], '48v')
    expect(growing['variants.0.price_tiers.1.price_per_unit_minor']).toBeDefined()
  })

  it('requires the first tier to start at the minimal duration', () => {
    const fields = validateVariants([
      { battery_count: 1, price_tiers: [tier(3, 100000)] },
    ], [1, 3, 7], '48v')

    expect(fields['variants.0.price_tiers.0.min_units']).toContain('1')
  })

  it('requires a battery type when a variant takes batteries', () => {
    const fields = validateVariants([
      { battery_count: 2, price_tiers: [tier(1, 100000)] },
    ], [1], null)

    expect(fields.battery_type).toBeDefined()
  })
})
