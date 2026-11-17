import type { components } from '../app/shared/api/schema'

export type PriceTier = components['schemas']['PriceTier']
export type RentalUnit = components['schemas']['Quote']['rental_unit']
export type PriceFrom = components['schemas']['PriceFrom']
export type LotVariant = components['schemas']['LotVariant']
export type LotVariantInput = components['schemas']['LotVariantInput']

/** Длительность единицы срока. Календарные месяцы не используются (D-21). */
export const UNIT_MS: Record<RentalUnit, number> = {
  day: 24 * 60 * 60 * 1000,
  hour: 60 * 60 * 1000,
}

export class PricingError extends Error {
  readonly code: 'validation_error' | 'rental_period_not_allowed'
  readonly fields?: Record<string, string>

  constructor(
    code: PricingError['code'],
    message: string,
    fields?: Record<string, string>,
  ) {
    super(message)
    this.name = 'PricingError'
    this.code = code
    this.fields = fields
  }
}

export interface PriceResult {
  totalMinor: number
  tierMinUnits: number
}

export interface RangePrice extends PriceResult {
  units: number
}

/** D-21: длительность округляется вверх до целых единиц. */
export const unitsBetween = (unit: RentalUnit, startMs: number, endMs: number): number =>
  Math.ceil((endMs - startMs) / UNIT_MS[unit])

/**
 * D-20: тир по сроку + round-up до более длинного пакета.
 * Тиры обязаны быть отсортированы и провалидированы до вызова.
 */
export const computePrice = (tiers: PriceTier[], units: number): PriceResult => {
  const matching = tiers.filter(tier => tier.min_units <= units)
  const tier = matching[matching.length - 1]

  if (!tier) {
    throw new PricingError('validation_error', 'Для срока нет тарифа')
  }

  let totalMinor = units * tier.price_per_unit_minor
  let tierMinUnits = tier.min_units

  for (const longer of tiers) {
    if (longer.min_units <= units) {
      continue
    }

    const packagePrice = longer.min_units * longer.price_per_unit_minor

    if (packagePrice < totalMinor) {
      totalMinor = packagePrice
      tierMinUnits = longer.min_units
    }
  }

  return { totalMinor, tierMinUnits }
}

export const minAllowedUnits = (allowedDurations: number[]): number =>
  allowedDurations.reduce((min, value) => Math.min(min, value), Number.POSITIVE_INFINITY)

/** D-22: минимум по активным вариантам, tie-break — меньший срок, затем меньше АКБ. */
export const priceFromOf = (variants: LotVariant[], unit: RentalUnit): PriceFrom | null => {
  let best: { amount: number; atUnits: number; batteryCount: number } | null = null

  for (const variant of variants) {
    if (!variant.is_active) {
      continue
    }

    for (const tier of variant.price_tiers) {
      const candidate = {
        amount: tier.price_per_unit_minor,
        atUnits: tier.min_units,
        batteryCount: variant.battery_count,
      }

      if (
        !best
        || candidate.amount < best.amount
        || (candidate.amount === best.amount && candidate.atUnits < best.atUnits)
        || (
          candidate.amount === best.amount
          && candidate.atUnits === best.atUnits
          && candidate.batteryCount < best.batteryCount
        )
      ) {
        best = candidate
      }
    }
  }

  if (!best) {
    return null
  }

  return {
    amount_minor: best.amount,
    per: unit,
    at_units: best.atUnits,
    battery_count: best.batteryCount,
  }
}

/** P-4: сроки непустые, целые, уникальные, по возрастанию, 1…365. */
export const validateAllowedDurations = (value: unknown): string | null => {
  if (!Array.isArray(value) || value.length === 0) {
    return 'Укажите хотя бы один срок'
  }

  const durations = value as unknown[]

  if (durations.some(item => !Number.isInteger(item) || (item as number) < 1 || (item as number) > 365)) {
    return 'Сроки — целые числа от 1 до 365'
  }

  const sorted = [...(durations as number[])].sort((left, right) => left - right)

  if (new Set(sorted).size !== sorted.length) {
    return 'Сроки не должны повторяться'
  }

  if (sorted.some((item, index) => item !== durations[index])) {
    return 'Сроки должны идти по возрастанию'
  }

  return null
}

/**
 * P-1…P-6: проверка вариантов. Возвращает `fields` в формате problem+json.
 */
export const validateVariants = (
  variants: LotVariantInput[] | undefined,
  allowedDurations: number[],
  batteryType: string | null,
): Record<string, string> => {
  const fields: Record<string, string> = {}

  if (!Array.isArray(variants) || variants.length === 0) {
    fields.variants = 'Нужен хотя бы один вариант'

    return fields
  }

  const seenCounts = new Set<number>()
  const minUnits = minAllowedUnits(allowedDurations)

  variants.forEach((variant, variantIndex) => {
    const prefix = `variants.${variantIndex}`

    if (!Number.isInteger(variant.battery_count) || variant.battery_count < 0) {
      fields[`${prefix}.battery_count`] = 'Количество АКБ — целое число ≥ 0'
    } else if (seenCounts.has(variant.battery_count)) {
      fields[`${prefix}.battery_count`] = 'Вариант с таким количеством АКБ уже есть'
    } else {
      seenCounts.add(variant.battery_count)
    }

    if (variant.battery_count > 0 && !batteryType) {
      fields.battery_type = 'Выберите тип АКБ'
    }

    const tiers = variant.price_tiers

    if (!Array.isArray(tiers) || tiers.length === 0) {
      fields[`${prefix}.price_tiers`] = 'Добавьте хотя бы один тариф'

      return
    }

    let previousMin = 0
    let previousPrice = Number.POSITIVE_INFINITY

    tiers.forEach((tier, tierIndex) => {
      const tierPrefix = `${prefix}.price_tiers.${tierIndex}`

      if (!Number.isInteger(tier.min_units) || tier.min_units < 1) {
        fields[`${tierPrefix}.min_units`] = 'Срок тарифа — целое число ≥ 1'
      } else if (tier.min_units === previousMin) {
        fields[`${tierPrefix}.min_units`] = 'Срок тарифа повторяется'
      } else if (tier.min_units < previousMin) {
        fields[`${tierPrefix}.min_units`] = 'Тарифы должны идти по возрастанию срока'
      }

      if (!Number.isInteger(tier.price_per_unit_minor) || tier.price_per_unit_minor < 1) {
        fields[`${tierPrefix}.price_per_unit_minor`] = 'Цена — целое число ≥ 1'
      } else if (tier.price_per_unit_minor > previousPrice) {
        fields[`${tierPrefix}.price_per_unit_minor`] = 'Цена за единицу не должна расти со сроком'
      }

      previousMin = tier.min_units
      previousPrice = tier.price_per_unit_minor
    })

    if (Number.isFinite(minUnits) && tiers[0]?.min_units !== minUnits) {
      fields[`${prefix}.price_tiers.0.min_units`] = `Первый тариф должен начинаться с минимального срока (${minUnits})`
    }
  })

  return fields
}

/** Цена аренды в моке: валидирует срок, затем считает D-20. */
export const priceForRange = (
  tiers: PriceTier[],
  allowedDurations: number[],
  unit: RentalUnit,
  startMs: number,
  endMs: number,
): RangePrice => {
  if (endMs <= startMs) {
    throw new PricingError('validation_error', 'Конец должен быть позже начала')
  }

  const units = unitsBetween(unit, startMs, endMs)
  const minUnits = minAllowedUnits(allowedDurations)

  if (units < minUnits) {
    throw new PricingError('rental_period_not_allowed', 'Минимальный срок аренды', {
      units: `Минимум ${minUnits}`,
    })
  }

  return { units, ...computePrice(tiers, units) }
}
