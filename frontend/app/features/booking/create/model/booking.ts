import type { Lot } from '~/entities/lot'

export type RentalUnit = 'hour' | 'day'

export interface DurationOption {
  label: string
  value: number
}

/** Часовая аренда — исключение, по умолчанию лот бронируют посуточно. */
export const unitOf = (model: Lot['rental_model']): RentalUnit =>
  model === 'hourly' ? 'hour' : 'day'

export const durationOptions = (unit: RentalUnit): DurationOption[] => unit === 'hour'
  ? [
      { label: '1 час', value: 1 },
      { label: '2 часа', value: 2 },
      { label: '4 часа', value: 4 },
      { label: '8 часов', value: 8 },
      { label: 'Сутки', value: 24 },
      { label: 'Неделя', value: 168 },
      { label: 'Свой срок', value: 0 },
    ]
  : [
      { label: '1 день', value: 1 },
      { label: '3 дня', value: 3 },
      { label: 'Неделя', value: 7 },
      { label: 'Месяц', value: 30 },
      { label: 'Свой срок', value: 0 },
    ]

export const addUnits = (start: Date, units: number, unit: RentalUnit): Date => {
  const ms = unit === 'hour' ? units * 60 * 60 * 1000 : units * 24 * 60 * 60 * 1000

  return new Date(start.getTime() + ms)
}

export const estimatePrice = (lot: Lot, units: number): number => lot.price_minor * units
