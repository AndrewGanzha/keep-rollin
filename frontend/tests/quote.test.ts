import { describe, expect, it } from 'vitest'
import { defaultVariantId, quoteOptions } from '~/features/booking/create/model/quote'
import { formatMoney } from '~/shared/lib/money'
import type { Quote } from '~/entities/lot/model/lot.types'

const quote: Quote = {
  lot_id: 'lot-1',
  start: '2026-11-20T00:00:00.000Z',
  end: '2026-11-27T00:00:00.000Z',
  units: 7,
  rental_unit: 'day',
  variants: [
    {
      variant_id: 'variant-1',
      battery_count: 1,
      price_total_minor: 280000,
      currency: 'RUB',
      tier_min_units: 7,
      available: true,
      unavailable_reason: null,
    },
    {
      variant_id: 'variant-2',
      battery_count: 2,
      price_total_minor: 350000,
      currency: 'RUB',
      tier_min_units: 7,
      available: false,
      unavailable_reason: 'battery_unavailable',
    },
  ],
}

describe('quote options', () => {
  it('builds labels, prices and reasons for every variant', () => {
    const options = quoteOptions(quote)

    expect(options).toHaveLength(2)
    expect(options[0]).toMatchObject({
      label: '1 АКБ',
      value: 'variant-1',
      price: formatMoney(280000),
      disabled: false,
      reason: '',
    })
    expect(options[1]).toMatchObject({
      label: '2 АКБ',
      disabled: true,
      reason: 'Свободных аккумуляторов на эти даты нет',
    })
  })

  it('selects the first available variant', () => {
    expect(defaultVariantId(quoteOptions(quote))).toBe('variant-1')
  })

  it('falls back to the first variant when all are unavailable', () => {
    const blocked: Quote = {
      ...quote,
      variants: quote.variants.map(variant => ({ ...variant, available: false })),
    }

    expect(defaultVariantId(quoteOptions(blocked))).toBe('variant-1')
  })

  it('explains an occupied slot', () => {
    const blocked: Quote = {
      ...quote,
      variants: quote.variants.map(variant => ({
        ...variant,
        available: false,
        unavailable_reason: 'slot_taken',
      })),
    }

    expect(quoteOptions(blocked)[0]?.reason).toBe('В эти дни лот занят')
  })

  it('returns an empty list without a quote', () => {
    expect(quoteOptions(null)).toEqual([])
    expect(defaultVariantId([])).toBe('')
  })
})
