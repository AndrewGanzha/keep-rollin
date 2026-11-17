import type { RentalUnit } from '~/entities/lot'

export interface DurationOption {
  label: string
  value: number
}

const dayLabel = (units: number): string => {
  if (units === 1) {
    return '1 день'
  }

  if (units === 3) {
    return '3 дня'
  }

  if (units === 7) {
    return 'Неделя'
  }

  if (units === 30) {
    return 'Месяц'
  }

  return `${units} дн.`
}

const hourLabel = (units: number): string => {
  if (units === 24) {
    return 'Сутки'
  }

  if (units === 7 * 24) {
    return 'Неделя'
  }

  return `${units} ч`
}

/** Пресеты срока — ровно `allowed_durations` лота (D-25), плюс «Свой срок». */
export const durationOptions = (unit: RentalUnit, allowedDurations: number[]): DurationOption[] => [
  ...[...allowedDurations]
    .sort((left, right) => left - right)
    .map(units => ({
      label: unit === 'hour' ? hourLabel(units) : dayLabel(units),
      value: units,
    })),
  { label: 'Свой срок', value: 0 },
]

export const addUnits = (start: Date, units: number, unit: RentalUnit): Date => {
  const ms = unit === 'hour' ? units * 60 * 60 * 1000 : units * 24 * 60 * 60 * 1000

  return new Date(start.getTime() + ms)
}

/** «3 дня», «7 суток», «2 часа» — для итога в диалоге брони. */
export const durationText = (units: number, unit: RentalUnit): string => {
  const mod10 = units % 10
  const mod100 = units % 100
  const isOne = mod10 === 1 && mod100 !== 11
  const isFew = mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)

  if (unit === 'hour') {
    return `${units} ${isOne ? 'час' : isFew ? 'часа' : 'часов'}`
  }

  return `${units} ${isOne ? 'день' : isFew ? 'дня' : 'суток'}`
}
