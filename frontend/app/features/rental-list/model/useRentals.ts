import { fetchMyRentals } from '~/entities/rental'
import { useApi } from '~/shared/api'

export const useRentals = async () => {
  const api = useApi()

  const request = useAsyncData('my-rentals', () => fetchMyRentals(api))
  await request

  return {
    data: request.data,
    pending: request.pending,
    error: request.error,
    refresh: request.refresh,
  }
}
