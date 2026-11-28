const relativePercent = new Intl.NumberFormat('ru-RU', {
  style: 'percent',
  maximumFractionDigits: 1,
  signDisplay: 'exceptZero',
})

export const formatRelativeChange = (delta: number, previous: number): string => {
  if (previous > 0) return relativePercent.format(delta / previous)
  return previous === 0 && delta === 0 ? relativePercent.format(0) : '—'
}
