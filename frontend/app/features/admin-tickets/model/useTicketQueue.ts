import {
  fetchAdminTicket,
  fetchAdminTickets,
  patchAdminTicket,
  type Ticket,
  type TicketPatchRequest,
  type TicketStatus,
} from '~/entities/ticket'
import { ApiError, useApi } from '~/shared/api'

export const useTicketQueue = async () => {
  const api = useApi()
  const toast = useToast()
  const status = ref<TicketStatus | undefined>()
  const details = shallowReactive<Record<string, {
    loading: boolean
    photos?: string[]
    error?: string
  }>>({})

  const request = useAsyncData(
    'admin-tickets',
    () => fetchAdminTickets(api, { status: status.value }),
    { watch: [status] },
  )
  await request

  const updating = ref(false)

  const loadDetails = async (id: string) => {
    const pending = { loading: true }
    details[id] = pending

    try {
      const ticket = await fetchAdminTicket(api, id)
      if (details[id] === pending) {
        details[id] = { loading: false, photos: ticket.photo_urls }
      }
    } catch (caught) {
      if (details[id] === pending) {
        const error = caught instanceof ApiError ? caught.message : 'Не удалось загрузить фото'
        details[id] = { loading: false, error }
      }
    }
  }

  const clearDetails = (id: string) => {
    delete details[id]
  }

  const update = async (ticket: Ticket, payload: TicketPatchRequest) => {
    updating.value = true

    try {
      await patchAdminTicket(api, ticket.id, payload)
      toast.add({ severity: 'success', summary: 'Тикет обновлён', life: 3000 })
      await request.refresh()
    } catch (caught) {
      const message = caught instanceof ApiError ? caught.message : 'Не удалось обновить тикет'
      toast.add({ severity: 'error', summary: message, life: 4000 })
      await request.refresh()
    } finally {
      updating.value = false
    }
  }

  return {
    data: request.data,
    pending: request.pending,
    error: request.error,
    refresh: request.refresh,
    status,
    updating,
    update,
    details,
    loadDetails,
    clearDetails,
  }
}
