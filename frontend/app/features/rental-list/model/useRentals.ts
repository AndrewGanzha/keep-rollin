import { fetchMyRentals, type RentalStatus } from '~/entities/rental'
import { useApi } from '~/shared/api'

export const useRentals = async () => {
  const api = useApi()
  const status = ref<RentalStatus | undefined>()

  const request = useAsyncData(
    'my-rentals',
    () => fetchMyRentals(api, status.value),
    { watch: [status] },
  )
  await request

  return {
    data: request.data,
    pending: request.pending,
    error: request.error,
    refresh: request.refresh,
    status,
  }
}
