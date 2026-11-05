const formatters = new Map<string, Intl.NumberFormat>()

/** Копейки → «1 500 ₽». */
export const formatMoney = (minor: number, currency = 'RUB'): string => {
  let formatter = formatters.get(currency)

  if (!formatter) {
    formatter = new Intl.NumberFormat('ru-RU', {
      style: 'currency',
      currency,
      maximumFractionDigits: 0,
    })
    formatters.set(currency, formatter)
  }

  return formatter.format(minor / 100)
}
