import { unwrap, type ApiClient } from '~/shared/api'
import type { components } from '~/shared/api/schema'
import type {
  CreateTicketRequest,
  Ticket,
  TicketPage,
  TicketPatchRequest,
  TicketStatus,
} from '../model/ticket.types'

export type TicketReceipt = components['schemas']['TicketReceipt']

export interface TicketQuery {
  status?: TicketStatus
  limit?: number
  offset?: number
}

export const fetchAdminTickets = async (
  api: ApiClient,
  query: TicketQuery = {},
): Promise<TicketPage> =>
  unwrap(await api.GET('/api/v1/admin/tickets', { params: { query } }))

export const fetchAdminTicket = async (api: ApiClient, id: string): Promise<Ticket> =>
  unwrap(await api.GET('/api/v1/admin/tickets/{id}', { params: { path: { id } } }))

export const patchAdminTicket = async (
  api: ApiClient,
  id: string,
  payload: TicketPatchRequest,
): Promise<Ticket> =>
  unwrap(
    await api.PATCH('/api/v1/admin/tickets/{id}', {
      params: { path: { id } },
      body: payload,
    }),
  )

export const fetchMyTickets = async (
  api: ApiClient,
  query: TicketQuery = {},
): Promise<TicketPage> =>
  unwrap(await api.GET('/api/v1/me/tickets', { params: { query } }))

export const createRentalTicket = async (
  api: ApiClient,
  rentalId: string,
  payload: CreateTicketRequest,
  idempotencyKey: string,
): Promise<TicketReceipt> =>
  unwrap(
    await api.POST('/api/v1/me/rentals/{id}/tickets', {
      params: { path: { id: rentalId }, header: { 'Idempotency-Key': idempotencyKey } },
      body: payload,
    }),
  )

export const uploadTicketPhoto = async (api: ApiClient, file: File): Promise<string> => {
  const upload = unwrap(
    await api.POST('/api/v1/files', {
      body: { file, purpose: 'ticket_photo' },
      bodySerializer: (body) => {
        const form = new FormData()
        form.set('file', body.file)
        form.set('purpose', body.purpose)
        return form
      },
    }),
  )
  return upload.file_id
}
