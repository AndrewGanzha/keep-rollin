/** Выбранный на ганте диапазон дней для блокировки (границы — ключи дней тенанта). */
export interface BlockRange {
  lotId: string
  lotName: string
  fromDay: string
  toDay: string
}
