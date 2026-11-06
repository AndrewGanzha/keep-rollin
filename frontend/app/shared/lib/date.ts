const dateTimeFormatters = new Map<string, Intl.DateTimeFormat>()
const timeFormatters = new Map<string, Intl.DateTimeFormat>()

/** ISO → «05.11, 14:30» в таймзоне тенанта. */
export const formatDateTime = (iso: string, timeZone?: string): string => {
  const key = timeZone ?? 'default'
  let formatter = dateTimeFormatters.get(key)

  if (!formatter) {
    formatter = new Intl.DateTimeFormat('ru-RU', {
      day: '2-digit',
      month: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      timeZone,
    })
    dateTimeFormatters.set(key, formatter)
  }

  return formatter.format(new Date(iso))
}

/** ISO → «14:30» в таймзоне тенанта. */
export const formatTime = (iso: string, timeZone?: string): string => {
  const key = timeZone ?? 'default'
  let formatter = timeFormatters.get(key)

  if (!formatter) {
    formatter = new Intl.DateTimeFormat('ru-RU', {
      hour: '2-digit',
      minute: '2-digit',
      timeZone,
    })
    timeFormatters.set(key, formatter)
  }

  return formatter.format(new Date(iso))
}

/** Секунды → «2 ч 15 мин» (для таймера аренды). */
export const formatDuration = (totalSeconds: number): string => {
  const minutes = Math.max(0, Math.floor(totalSeconds / 60))
  const hours = Math.floor(minutes / 60)
  const restMinutes = minutes % 60

  if (hours === 0) {
    return `${restMinutes} мин`
  }

  return restMinutes === 0 ? `${hours} ч` : `${hours} ч ${restMinutes} мин`
}
