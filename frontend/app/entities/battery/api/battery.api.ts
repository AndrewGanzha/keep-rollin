import { unwrap, type ApiClient } from '~/shared/api'
import type { BatteryStock, UpdateBatteryStockRequest } from '../model/battery.types'

export const fetchBatteryStock = async (api: ApiClient): Promise<BatteryStock[]> =>
  unwrap(await api.GET('/api/v1/admin/batteries'))

export const updateBatteryStock = async (
  api: ApiClient,
  batteryType: string,
  payload: UpdateBatteryStockRequest,
): Promise<BatteryStock> =>
  unwrap(
    await api.PATCH('/api/v1/admin/batteries/{battery_type}', {
      params: { path: { battery_type: batteryType } },
      body: payload,
    }),
  )
