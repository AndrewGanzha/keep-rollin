import { unwrap, type ApiClient } from '~/shared/api'
import type {
  AdminSchedule,
  CreateLotBlockRequest,
  LotBlock,
  ScheduleInterval,
} from '../model/schedule.types'

export interface ScheduleQuery {
  from: string
  to: string
  category_id?: string
}

export const fetchSchedule = async (
  api: ApiClient,
  query: ScheduleQuery,
): Promise<AdminSchedule> =>
  unwrap(await api.GET('/api/v1/admin/schedule', { params: { query } }))

export const createLotBlock = async (
  api: ApiClient,
  lotId: string,
  payload: CreateLotBlockRequest,
): Promise<LotBlock> =>
  unwrap(
    await api.POST('/api/v1/admin/lots/{id}/blocks', {
      params: { path: { id: lotId } },
      body: payload,
    }),
  )

export const deleteLotBlock = async (
  api: ApiClient,
  lotId: string,
  blockId: string,
): Promise<void> => {
  const result = await api.DELETE('/api/v1/admin/lots/{id}/blocks/{block_id}', {
    params: { path: { id: lotId, block_id: blockId } },
  })

  if (result.response.status !== 204) {
    unwrap(result)
  }
}

export const isRentalInterval = (interval: ScheduleInterval): interval is Extract<ScheduleInterval, { kind: 'rental' }> =>
  interval.kind === 'rental'

export const isBlockInterval = (interval: ScheduleInterval): interval is Extract<ScheduleInterval, { kind: 'block' }> =>
  interval.kind === 'block'
