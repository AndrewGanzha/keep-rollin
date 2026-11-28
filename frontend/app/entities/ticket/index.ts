export {
  createRentalTicket,
  fetchAdminTicket,
  fetchAdminTickets,
  fetchMyTickets,
  patchAdminTicket,
  uploadTicketPhoto,
  type TicketQuery,
  type TicketReceipt,
} from './api/ticket.api'
export type {
  CreateTicketRequest,
  Ticket,
  TicketCategory,
  TicketPage,
  TicketPatchRequest,
  TicketStatus,
} from './model/ticket.types'
