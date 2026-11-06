import type { RentalStatus } from './rental.types'

export const rentalStatusLabels: Record<RentalStatus, string> = {
  booked: 'Забронировано',
  active: 'Активна',
  overdue: 'Просрочена',
  completed: 'Завершена',
  cancelled: 'Отменена',
}

export const rentalStatusSeverity: Record<
  RentalStatus,
  'success' | 'info' | 'warn' | 'danger' | 'secondary'
> = {
  booked: 'info',
  active: 'success',
  overdue: 'danger',
  completed: 'secondary',
  cancelled: 'secondary',
}
