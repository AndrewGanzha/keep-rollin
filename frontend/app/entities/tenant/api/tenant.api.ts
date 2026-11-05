import { unwrap, type ApiClient } from '~/shared/api'
import type { Tenant } from '../model/tenant.types'

export const fetchTenant = async (api: ApiClient): Promise<Tenant> =>
  unwrap(await api.GET('/api/v1/public/tenant'))

export const useTenant = () => useState<Tenant | null>('tenant', () => null)
