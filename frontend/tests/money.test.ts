import { describe, expect, it } from 'vitest'
import { formatMoney } from '../app/shared/lib/money'

describe('formatMoney', () => {
  it('renders minor units as rubles', () => {
    expect(formatMoney(45_000)).toMatch(/450/)
    expect(formatMoney(45_000)).toContain('₽')
  })

  it('keeps zero', () => {
    expect(formatMoney(0)).toMatch(/0/)
  })
})
