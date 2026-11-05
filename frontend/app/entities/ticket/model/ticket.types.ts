import type { components } from '~/shared/api/schema'

export type Ticket = components['schemas']['Ticket']
export type TicketPage = components['schemas']['TicketPage']
export type TicketStatus = Ticket['status']
export type TicketCategory = Ticket['category']
export type TicketPatchRequest = components['schemas']['TicketPatchRequest']
