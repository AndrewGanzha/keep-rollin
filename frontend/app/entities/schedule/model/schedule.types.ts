import type { components } from '~/shared/api/schema'

export type AdminSchedule = components['schemas']['AdminSchedule']
export type ScheduleLot = components['schemas']['ScheduleLot']
export type ScheduleRentalInterval = components['schemas']['ScheduleRentalInterval']
export type ScheduleBlockInterval = components['schemas']['ScheduleBlockInterval']
export type ScheduleInterval = ScheduleRentalInterval | ScheduleBlockInterval
export type LotBlock = components['schemas']['LotBlock']
export type CreateLotBlockRequest = components['schemas']['CreateLotBlockRequest']
export type BatteryStock = components['schemas']['BatteryStock']
