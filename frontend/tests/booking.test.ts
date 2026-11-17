import { describe, expect, it } from 'vitest'
import { addUnits, durationOptions, durationText } from '../app/features/booking/create/model/booking'

describe('booking units', () => {
  it('builds presets from allowed durations and appends the custom option', () => {
    const options = durationOptions('day', [1, 3, 7, 30])

    expect(options.map(option => option.value)).toEqual([1, 3, 7, 30, 0])
    expect(options[0]).toEqual({ label: '1 день', value: 1 })
    expect(options[2]).toEqual({ label: 'Неделя', value: 7 })
    expect(options[3]).toEqual({ label: 'Месяц', value: 30 })
    expect(options[4]).toEqual({ label: 'Свой срок', value: 0 })
  })

  it('does not offer presets that the landlord disabled', () => {
    const options = durationOptions('day', [7, 30])

    expect(options.map(option => option.value)).toEqual([7, 30, 0])
  })

  it('labels whole days as сутки for hourly lots', () => {
    const options = durationOptions('hour', [1, 3, 24])

    expect(options[2]).toEqual({ label: 'Сутки', value: 24 })
  })

  it('adds days and hours', () => {
    const start = new Date('2026-11-06T10:00:00.000Z')

    expect(addUnits(start, 1, 'day').toISOString()).toBe('2026-11-07T10:00:00.000Z')
    expect(addUnits(start, 2, 'hour').toISOString()).toBe('2026-11-06T12:00:00.000Z')
  })

  it('declines durations in Russian', () => {
    expect(durationText(1, 'day')).toBe('1 день')
    expect(durationText(3, 'day')).toBe('3 дня')
    expect(durationText(7, 'day')).toBe('7 суток')
    expect(durationText(21, 'day')).toBe('21 день')
    expect(durationText(1, 'hour')).toBe('1 час')
    expect(durationText(2, 'hour')).toBe('2 часа')
    expect(durationText(11, 'hour')).toBe('11 часов')
    expect(durationText(22, 'hour')).toBe('22 часа')
  })
})
