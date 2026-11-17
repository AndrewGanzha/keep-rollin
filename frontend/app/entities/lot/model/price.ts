import { formatMoney } from '~/shared/lib'
import type { Lot, QuoteVariant } from './lot.types'

/** «от 400 ₽/сут»; null превращается в нейтральную подпись, а не в 0. */
export const priceFromLabel = (lot: Lot): string => lot.price_from
  ? `от ${formatMoney(lot.price_from.amount_minor, lot.currency)}/${lot.price_from.per === 'day' ? 'сут' : 'час'}`
  : 'Цена по запросу'

/**
 * Подпись к «от»: нужна, если цена действует не с первой единицы
 * или в лоте несколько вариантов (D-22).
 */
export const priceFromNote = (lot: Lot): string | null => {
  const price = lot.price_from

  if (!price) {
    return null
  }

  const activeVariants = lot.variants.filter(variant => variant.is_active).length

  if (price.at_units <= 1 && activeVariants <= 1) {
    return null
  }

  const unitLabel = price.per === 'day' ? 'суток' : 'часов'
  const batteryLabel = price.battery_count > 0 ? `${price.battery_count} АКБ` : 'без АКБ'

  return `при аренде от ${price.at_units} ${unitLabel}, ${batteryLabel}`
}

export const variantLabel = (batteryCount: number): string =>
  batteryCount > 0 ? `${batteryCount} АКБ` : 'Без АКБ'

export const unavailableReasonText = (
  reason: QuoteVariant['unavailable_reason'],
): string => {
  switch (reason) {
    case 'battery_unavailable':
      return 'Свободных аккумуляторов на эти даты нет'
    case 'slot_taken':
      return 'В эти дни лот занят'
    case 'rental_period_not_allowed':
      return 'Срок короче минимального'
    default:
      return ''
  }
}
