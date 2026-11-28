import { randomUUID } from 'node:crypto'
import type { components } from '../app/shared/api/schema'

type Schemas = components['schemas']
type OfferVersion = Schemas['OfferVersionDTO']
type OfferAcceptance = Schemas['OfferAcceptanceDTO']

const objectBody = (body: unknown): Record<string, unknown> | null =>
  body !== null && typeof body === 'object' && !Array.isArray(body) ? body as Record<string, unknown> : null

const validString = (value: unknown, min: number, max: number): value is string => {
  if (typeof value !== 'string' || value.includes('\0')) return false
  const length = [...value].length
  return length >= min && length <= max
}

export function parseRegistration(input: unknown) {
  const { email: rawEmail, password, name, phone } = objectBody(input) ?? {}
  const email = typeof rawEmail === 'string' ? rawEmail.trim().toLowerCase() : ''
  const fields: Record<string, string> = {}
  if (!validString(rawEmail, 1, 254) || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
    fields.email = 'Укажите корректный email'
  }
  if (name != null && !validString(name, 1, 120)) fields.name = 'От 1 до 120 символов'
  if (phone != null && !validString(phone, 0, 32)) fields.phone = 'До 32 символов'
  if (!validString(password, 8, 128)) return { fields: { ...fields, password: 'От 8 до 128 символов' } }
  if (Object.keys(fields).length) return { fields }
  const payload: Schemas['RegisterRequest'] = {
    email,
    password,
    name: typeof name === 'string' ? name : null,
    phone: typeof phone === 'string' ? phone : null,
  }
  return { payload }
}

export function parseOfferText(input: unknown): Partial<Schemas['CreateOfferRequest']> | null {
  const body = objectBody(input)
  if (!body || !Object.keys(body).length || Object.keys(body).some(key => key !== 'title' && key !== 'body')) {
    return null
  }
  const updates: Partial<Schemas['CreateOfferRequest']> = {}
  for (const [key, max] of [['title', 200], ['body', 20000]] as const) {
    if (!Object.hasOwn(body, key)) continue
    const value = body[key]
    if (!validString(value, 1, max) || !value.trim()) return null
    updates[key] = value.trim()
  }
  return updates
}

export const parseOfferId = (value: unknown): string | null =>
  typeof value === 'string' && /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(value)
    ? value.toLowerCase()
    : null

export function parseAcceptance(input: unknown): Schemas['AcceptOfferRequest'] | null {
  const payload = objectBody(input)
  if (!payload || Object.keys(payload).length !== 1) return null
  const id = parseOfferId(payload.offer_version_id)
  return id ? { offer_version_id: id } : null
}

export function parseOfferPage(query: Record<string, unknown>) {
  const { limit = '20', offset = '0' } = query
  if (typeof limit !== 'string' || typeof offset !== 'string' || !/^\d+$/.test(limit) || !/^\d+$/.test(offset)) {
    return null
  }
  const page = { limit: Number(limit), offset: Number(offset) }
  return page.limit >= 1 && page.limit <= 100 && BigInt(offset) <= 9223372036854775807n ? page : null
}

export function createMockOffers(seed: OfferVersion, acceptedUserIds: string[]) {
  const versions = [seed]
  const acceptances = new Map<string, OfferAcceptance[]>()

  const current = (): Schemas['PublicOfferDTO'] | undefined => {
    const offer = versions.find(item => item.status === 'active')
    if (!offer?.published_at) return undefined
    const { id, version, title, body, published_at } = offer
    return { id, version, title, body, published_at }
  }

  const history = (userId: string) => acceptances.get(userId) ?? []

  function recordAcceptance(userId: string, offer: OfferVersion, acceptedAt: string, ip: string | null): OfferAcceptance {
    const previous = history(userId)
    const existing = previous.find(item => item.offer_version_id === offer.id)
    if (existing) return existing
    const acceptance: OfferAcceptance = {
      id: randomUUID(),
      offer_version_id: offer.id,
      version: offer.version,
      accepted_at: acceptedAt,
      ip,
    }
    acceptances.set(userId, [acceptance, ...previous])
    return acceptance
  }

  for (const userId of acceptedUserIds) {
    recordAcceptance(userId, seed, seed.published_at ?? seed.updated_at, null)
  }

  return {
    current,
    history,
    hasAcceptedCurrent(userId: string) {
      const id = current()?.id
      return history(userId).some(item => item.offer_version_id === id)
    },
    list(limit: number, offset: number): Schemas['OfferPageDTO'] {
      return { items: versions.slice(offset, offset + limit), total: versions.length, limit, offset }
    },
    create(text: Schemas['CreateOfferRequest']): OfferVersion {
      const now = new Date().toISOString()
      const draft: OfferVersion = {
        ...text,
        id: randomUUID(),
        version: (versions[0]?.version ?? 0) + 1,
        status: 'draft',
        published_at: null,
        created_at: now,
        updated_at: now,
      }
      versions.unshift(draft)
      return draft
    },
    update(id: string, changes: Partial<Schemas['CreateOfferRequest']>) {
      const offer = versions.find(item => item.id === id)
      if (!offer) return 'not_found'
      if (offer.status !== 'draft') return 'offer_not_editable'
      Object.assign(offer, changes, { updated_at: new Date().toISOString() })
      return offer
    },
    publish(id: string) {
      const offer = versions.find(item => item.id === id)
      if (!offer) return 'not_found'
      if (offer.status !== 'draft') return 'offer_not_editable'
      const now = new Date().toISOString()
      const active = versions.find(item => item.status === 'active')
      if (active) Object.assign(active, { status: 'archived', updated_at: now })
      Object.assign(offer, { status: 'active', published_at: now, updated_at: now })
      return offer
    },
    accept(userId: string, id: string, ip: string | null) {
      const offer = versions.find(item => item.id === id)
      if (!offer) return 'not_found'
      if (offer.status !== 'active') return 'offer_not_active'
      return recordAcceptance(userId, offer, new Date().toISOString(), ip)
    },
  }
}
