import { describe, expect, it } from 'vitest'
import { formatDuration } from '../app/shared/lib/date'

describe('formatDuration', () => {
  it('formats minutes only', () => {
    expect(formatDuration(45 * 60)).toBe('45 мин')
  })

  it('formats hours and minutes', () => {
    expect(formatDuration(2 * 3600 + 15 * 60)).toBe('2 ч 15 мин')
  })

  it('never goes negative', () => {
    expect(formatDuration(-100)).toBe('0 мин')
  })
})
