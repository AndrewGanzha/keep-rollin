import { type ApiClient, unwrap } from '~/shared/api'
import type { components } from '~/shared/api/schema'

export type PublicOffer = components['schemas']['PublicOfferDTO']
export type OfferVersion = components['schemas']['OfferVersionDTO']
export type OfferPage = components['schemas']['OfferPageDTO']
export type OfferDraft = components['schemas']['CreateOfferRequest']
type UpdateOffer = components['schemas']['UpdateOfferRequest']

export const fetchCurrentOffer = async (api: ApiClient): Promise<PublicOffer> =>
  unwrap(await api.GET('/api/v1/public/offers/current', {
    cache: 'no-store',
    headers: { 'Cache-Control': 'no-cache' },
  }))

export const acceptOffer = async (api: ApiClient, offerId: string) =>
  unwrap(await api.POST('/api/v1/me/offer-acceptances', { body: { offer_version_id: offerId } }))

export const listAdminOffers = async (api: ApiClient, limit: number, offset: number): Promise<OfferPage> =>
  unwrap(await api.GET('/api/v1/admin/offers', { params: { query: { limit, offset } } }))

export const createOffer = async (api: ApiClient, body: OfferDraft): Promise<OfferVersion> =>
  unwrap(await api.POST('/api/v1/admin/offers', { body }))

export const updateOffer = async (api: ApiClient, offerId: string, body: UpdateOffer): Promise<OfferVersion> =>
  unwrap(await api.PATCH('/api/v1/admin/offers/{offer_id}', { params: { path: { offer_id: offerId } }, body }))

export const publishOffer = async (api: ApiClient, offerId: string): Promise<OfferVersion> =>
  unwrap(await api.POST('/api/v1/admin/offers/{offer_id}/publish', { params: { path: { offer_id: offerId } } }))
