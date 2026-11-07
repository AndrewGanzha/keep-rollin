import { unwrap, type ApiClient } from '~/shared/api'
import type {
  CreateTicketRequest,
  Ticket,
  TicketPage,
  TicketPatchRequest,
  TicketStatus,
} from '../model/ticket.types'

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
): Promise<Ticket> =>
  unwrap(
    await api.POST('/api/v1/me/rentals/{id}/tickets', {
      params: { path: { id: rentalId } },
      body: payload,
    }),
  )
