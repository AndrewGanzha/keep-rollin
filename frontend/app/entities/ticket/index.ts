export {
  createRentalTicket,
  fetchAdminTickets,
  fetchMyTickets,
  patchAdminTicket,
  type TicketQuery,
} from './api/ticket.api'
export type {
  CreateTicketRequest,
  Ticket,
  TicketCategory,
  TicketPage,
  TicketPatchRequest,
  TicketStatus,
} from './model/ticket.types'
