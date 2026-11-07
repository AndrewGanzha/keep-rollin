import { fetchMyTickets } from '~/entities/ticket'
import { useApi } from '~/shared/api'

export const useMyTickets = async () => {
  const api = useApi()

  const request = useAsyncData('my-tickets', () => fetchMyTickets(api))
  await request

  return {
    data: request.data,
    pending: request.pending,
    error: request.error,
    refresh: request.refresh,
  }
}
