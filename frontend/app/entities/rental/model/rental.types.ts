import type { components } from '~/shared/api/schema'

export type Rental = components['schemas']['Rental']
export type RentalPage = components['schemas']['RentalPage']
export type CreateRentalRequest = components['schemas']['CreateRentalRequest']
export type RentalStatus = Rental['status']
export type AdminRental = components['schemas']['AdminRental']
export type AdminRentalPage = components['schemas']['AdminRentalPage']
export type AdminRentalStatus = AdminRental['status']
export type CloseRentalRequest = components['schemas']['CloseRentalRequest']
export type CancelAdminRentalRequest = components['schemas']['CancelAdminRentalRequest']
