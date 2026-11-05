import type { components } from '~/shared/api/schema'

export type Rental = components['schemas']['Rental']
export type RentalPage = components['schemas']['RentalPage']
export type CreateRentalRequest = components['schemas']['CreateRentalRequest']
export type RentalStatus = Rental['status']
