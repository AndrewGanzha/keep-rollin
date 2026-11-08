import type { components } from '~/shared/api/schema'

export type Lot = components['schemas']['Lot']
export type LotPage = components['schemas']['LotPage']
export type Availability = components['schemas']['Availability']
export type BusyInterval = components['schemas']['BusyInterval']
export type CreateLotRequest = components['schemas']['CreateLotRequest']
export type LotStatusRequest = components['schemas']['LotStatusRequest']
export type LotStatus = Lot['status']
