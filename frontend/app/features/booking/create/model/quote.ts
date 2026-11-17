import { formatMoney } from '~/shared/lib'
import { unavailableReasonText, variantLabel } from '~/entities/lot/model/price'
import type { Quote } from '~/entities/lot/model/lot.types'

export interface QuoteOption {
  label: string
  value: string
  price: string
  disabled: boolean
  reason: string
}

/** Варианты для SelectButton: цена и причина недоступности в подписи. */
export const quoteOptions = (quote: Quote | null): QuoteOption[] =>
  (quote?.variants ?? []).map(variant => ({
    label: variantLabel(variant.battery_count),
    value: variant.variant_id,
    price: formatMoney(variant.price_total_minor, variant.currency),
    disabled: !variant.available,
    reason: unavailableReasonText(variant.unavailable_reason),
  }))

export const defaultVariantId = (options: QuoteOption[]): string =>
  options.find(option => !option.disabled)?.value ?? options[0]?.value ?? ''
