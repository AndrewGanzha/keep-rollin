import { createRentalTicket, type CreateTicketRequest, type Ticket } from '~/entities/ticket'
import { ApiError, useApi } from '~/shared/api'

export const useCreateTicket = () => {
  const api = useApi()
  const toast = useToast()

  const pending = ref(false)

  const create = async (rentalId: string, payload: CreateTicketRequest): Promise<Ticket | null> => {
    pending.value = true

    try {
      const ticket = await createRentalTicket(api, rentalId, payload)
      toast.add({ severity: 'success', summary: `Обращение №${ticket.id.slice(-4)} принято`, life: 4000 })
      return ticket
    } catch (caught) {
      const message = caught instanceof ApiError
        ? caught.message
        : 'Не удалось отправить обращение'
      toast.add({ severity: 'error', summary: message, life: 4000 })
      return null
    } finally {
      pending.value = false
    }
  }

  return { create, pending }
}
