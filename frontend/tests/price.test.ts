import { describe, expect, it } from 'vitest'
import { priceFromLabel, priceFromNote, variantLabel } from '~/entities/lot/model/price'
import type { Lot, LotVariant, PriceFrom } from '~/entities/lot/model/lot.types'
import { formatMoney } from '~/shared/lib/money'

const makeVariant = (batteryCount: number): LotVariant => ({
  id: `variant-${batteryCount}`,
  battery_count: batteryCount,
  is_active: true,
  price_tiers: [{ min_units: 1, price_per_unit_minor: 40000 }],
})

const makeLot = (price: PriceFrom | null, variants: LotVariant[], unit: Lot['rental_unit'] = 'day'): Lot => ({
  id: 'lot-1',
  slug: 'urban-one',
  name: 'Urban One',
  category_id: 'category-1',
  photos: [],
  characteristics: {},
  rental_unit: unit,
  battery_type: '48v',
  variants,
  allowed_durations: [1],
  price_from: price,
  currency: 'RUB',
  status: 'active',
  is_bookable: true,
  version: 1,
})

const from = (atUnits: number, batteryCount = 1, per: 'day' | 'hour' = 'day'): PriceFrom => ({
  amount_minor: 40000,
  per,
  at_units: atUnits,
  battery_count: batteryCount,
})

describe('витрина «от»', () => {
  it('renders the minimal per-unit price with the unit suffix', () => {
    expect(priceFromLabel(makeLot(from(7), [makeVariant(1)])))
      .toBe(`от ${formatMoney(40000)}/сут`)
    expect(priceFromLabel(makeLot(from(24, 1, 'hour'), [makeVariant(1)], 'hour')))
      .toBe(`от ${formatMoney(40000)}/час`)
  })

  it('falls back to a neutral label without a price', () => {
    expect(priceFromLabel(makeLot(null, []))).toBe('Цена по запросу')
  })

  it('hides the note for a single variant starting at one unit', () => {
    expect(priceFromNote(makeLot(from(1), [makeVariant(1)]))).toBeNull()
  })

  it('shows the duration and battery condition when the price starts later', () => {
    expect(priceFromNote(makeLot(from(7), [makeVariant(1)])))
      .toBe('при аренде от 7 суток, 1 АКБ')
  })

  it('shows the note for several variants even at the first unit', () => {
    expect(priceFromNote(makeLot(from(1), [makeVariant(1), makeVariant(2)])))
      .toBe('при аренде от 1 суток, 1 АКБ')
  })

  it('labels battery-free variants', () => {
    expect(variantLabel(0)).toBe('Без АКБ')
    expect(variantLabel(2)).toBe('2 АКБ')
  })
})
