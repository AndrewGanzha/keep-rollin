import { once } from 'node:events'
import type { Server } from 'node:http'
import { createMockServer } from 'mock-config-server'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { components } from '../app/shared/api/schema'

type Schemas = components['schemas']

const publicOffer = '/public/offers/current'
const adminOffers = '/admin/offers'
const acceptances = '/me/offer-acceptances'
const session = '/auth/session'
const password = 'Cedar-Sunset-227!'

let server: Server
let origin: string

beforeEach(async () => {
  vi.resetModules()
  const { default: config } = await import('../mock-server.config')
  server = createMockServer(config).listen(0, '127.0.0.1')
  await once(server, 'listening')
  const address = server.address()
  if (!address || typeof address === 'string') throw new Error('Mock server has no loopback port')
  origin = `http://127.0.0.1:${address.port}/api/v1`
})

afterEach(async () => {
  await new Promise<void>((resolve, reject) => {
    server.close(error => error ? reject(error) : resolve())
    server.closeAllConnections()
  })
})

async function request<T>(path: string, { method = 'GET', token, body }: {
  method?: string
  token?: string
  body?: unknown
} = {}) {
  const headers = new Headers()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (body !== undefined) headers.set('Content-Type', 'application/json')
  const response = await fetch(origin + path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const json = (response.status === 204 ? undefined : await response.json()) as T
  return { response, json }
}

async function expectProblem(
  status: number,
  code: string,
  path: string,
  options?: Parameters<typeof request>[1],
) {
  const { response, json } = await request<Schemas['Problem']>(path, options)
  expect(response.status).toBe(status)
  expect(response.headers.get('Content-Type')).toContain('application/problem+json')
  expect(json).toMatchObject({ status, code })
}

async function login(email: string) {
  const { response, json } = await request<Schemas['LoginResponse']>('/auth/login', {
    method: 'POST', body: { email, password },
  })
  expect(response.status).toBe(200)
  if (json.access_token) return json.access_token

  expect(json.mfa_token).toBeTruthy()
  const endpoint = json.mfa_setup_required ? 'confirm' : 'verify'
  const result = await request<Schemas['LoginResponse']>(`/auth/mfa/${endpoint}`, {
    method: 'POST', body: { mfa_token: json.mfa_token, code: '123456' },
  })
  expect(result.response.status).toBe(200)
  expect(result.json.access_token).toBeTruthy()
  return result.json.access_token!
}

async function bookingForDate(daysFromNow: number): Promise<Schemas['CreateRentalRequest']> {
  const { json } = await request<Schemas['LotPage']>('/public/lots')
  const lot = json.items.find(item => item.slug === 'spare-48v')!
  const dayMs = 86400000
  const start = Date.now() + daysFromNow * dayMs
  return {
    lot_id: lot.id,
    variant_id: lot.variants.find(variant => variant.is_active)!.id,
    start_time: new Date(start).toISOString(),
    end_time: new Date(start + dayMs).toISOString(),
  }
}

describe('stateful onboarding mock HTTP API', () => {
  it('registers a pending rider, preserves session identity and keeps acceptance history private', async () => {
    const { json: current } = await request<Schemas['PublicOfferDTO']>(publicOffer)
    const registration = { email: ' Smoke-Rider@example.test ', name: ' Smoke Rider ', password, phone: '+12025550123' }
    await expectProblem(422, 'validation_error', '/auth/register', {
      method: 'POST', body: { ...registration, password: 'too low' },
    })
    await expectProblem(401, 'invalid_credentials', '/auth/login', {
      method: 'POST', body: { email: registration.email, password },
    })
    const created = await request<Schemas['LoginResponse']>('/auth/register', { method: 'POST', body: registration })
    expect(created.response.status).toBe(201)
    expect(created.json.user).toMatchObject({ email: 'smoke-rider@example.test', name: 'Smoke Rider', role: 'user', verification_status: 'pending' })
    const token = created.json.access_token!
    expect(token).toBeTruthy()
    expect((await request<Schemas['Session']>(session, { token })).json.offer_accepted).toBe(false)
    expect((await request<Schemas['OfferAcceptanceDTO'][]>(acceptances, { token })).json).toEqual([])
    const booking = { method: 'POST', token, body: await bookingForDate(21) }
    await expectProblem(403, 'verification_required', '/rentals', booking)
    await expectProblem(409, 'email_taken', '/auth/register', {
      method: 'POST', body: { ...registration, email: 'smoke-rider@example.test' },
    })
    await expectProblem(401, 'invalid_credentials', '/auth/login', {
      method: 'POST', body: { email: registration.email, password: 'Different-Pass!' },
    })
    const loginToken = await login(registration.email)
    expect((await request<Schemas['Session']>(session, { token: loginToken })).json.user.id).toBe(created.json.user?.id)

    await expectProblem(401, 'token_invalid', acceptances)
    await expectProblem(422, 'validation_error', acceptances, {
      method: 'POST', token, body: { offer_version_id: current.id, user_id: 'someone else' },
    })
    const acceptance = { method: 'POST', token, body: { offer_version_id: current.id } }
    const [first, repeated] = await Promise.all([
      request<Schemas['OfferAcceptanceDTO']>(acceptances, acceptance),
      request<Schemas['OfferAcceptanceDTO']>(acceptances, acceptance),
    ])
    expect(first.response.status).toBe(200)
    expect(first.json).toMatchObject({ offer_version_id: current.id, version: current.version, ip: '127.0.0.1' })
    expect(repeated.json).toEqual(first.json)
    expect((await request<Schemas['OfferAcceptanceDTO'][]>(acceptances, { token: loginToken })).json).toEqual([first.json])
    expect((await request<Schemas['Session']>(session, { token })).json.offer_accepted).toBe(true)
    await expectProblem(403, 'verification_required', '/rentals', booking)

    const other = await request<Schemas['LoginResponse']>('/auth/register', {
      method: 'POST', body: { ...registration, email: 'other-rider@example.test' },
    })
    expect((await request<Schemas['OfferAcceptanceDTO'][]>(acceptances, { token: other.json.access_token! })).json).toEqual([])

    expect((await request('/auth/password/forgot', { method: 'POST', body: { email: registration.email } })).response.status).toBe(202)
    const newPassword = 'New-Cedar-Sunset-228!'
    const reset = await request('/auth/password/reset', {
      method: 'POST', body: { token: 'mock-password-reset-token', password: newPassword },
    })
    expect(reset.response.status).toBe(204)
    await expectProblem(401, 'invalid_credentials', '/auth/login', {
      method: 'POST', body: { email: registration.email, password },
    })
    const afterReset = await request<Schemas['LoginResponse']>('/auth/login', {
      method: 'POST', body: { email: registration.email, password: newPassword },
    })
    expect(afterReset.response.status).toBe(200)
    expect(afterReset.json.user?.id).toBe(created.json.user?.id)
  })

  it('publishes draft versions for the owner and gates booking until the new acceptance', async () => {
    const rider = await login('rider@example.com')
    const owner = await login('owner@example.com')
    const admin = await login('admin@example.com')
    const { json: current } = await request<Schemas['PublicOfferDTO']>(publicOffer)
    const input = { title: ' New terms ', body: ' ## Terms\n\n- First revision ' }

    await expectProblem(401, 'token_invalid', adminOffers)
    await expectProblem(403, 'forbidden_role', adminOffers, { token: rider })
    await expectProblem(403, 'forbidden_role', adminOffers, { token: admin })
    await expectProblem(403, 'forbidden_role', adminOffers, { method: 'POST', token: admin, body: input })
    await expectProblem(422, 'validation_error', `${adminOffers}?limit=0`, { token: owner })
    await expectProblem(422, 'validation_error', adminOffers, { method: 'POST', token: owner, body: { ...input, body: ' ' } })
    expect((await request<Schemas['Session']>(session, { token: rider })).json.offer_accepted).toBe(true)
    const beforePublish = await request<Schemas['Rental']>('/rentals', {
      method: 'POST', token: rider, body: await bookingForDate(21),
    })
    expect(beforePublish.response.status).toBe(201)

    const draft = await request<Schemas['OfferVersionDTO']>(adminOffers, { method: 'POST', token: owner, body: input })
    expect(draft.response.status).toBe(201)
    expect(draft.json).toMatchObject({ status: 'draft', published_at: null, version: current.version + 1, title: 'New terms' })
    const draftPath = `${adminOffers}/${draft.json.id}`
    await expectProblem(403, 'forbidden_role', draftPath, { method: 'PATCH', token: admin, body: { title: 'Denied' } })
    await expectProblem(403, 'forbidden_role', `${draftPath}/publish`, { method: 'POST', token: admin })
    await expectProblem(422, 'validation_error', draftPath, { method: 'PATCH', token: owner, body: { body: null } })
    await expectProblem(409, 'offer_not_active', acceptances, { method: 'POST', token: rider, body: { offer_version_id: draft.json.id } })
    await expectProblem(404, 'not_found', acceptances, {
      method: 'POST', token: rider, body: { offer_version_id: '00000000-0000-4000-8000-000000000001' },
    })
    expect((await request<Schemas['PublicOfferDTO']>(publicOffer)).json).toEqual(current)

    const revisedBody = '# Revised terms\n\n- Second revision'
    const edited = await request<Schemas['OfferVersionDTO']>(draftPath, { method: 'PATCH', token: owner, body: { body: revisedBody } })
    expect(edited.json).toMatchObject({ id: draft.json.id, body: revisedBody, status: 'draft' })
    const published = await request<Schemas['OfferVersionDTO']>(`${draftPath}/publish`, { method: 'POST', token: owner })
    expect(published.json).toMatchObject({ id: draft.json.id, status: 'active', published_at: expect.any(String) })
    expect((await request<Schemas['PublicOfferDTO']>(publicOffer)).json).toEqual({
      id: draft.json.id, version: draft.json.version, title: draft.json.title, body: revisedBody, published_at: published.json.published_at,
    })
    const { json: page } = await request<Schemas['OfferPageDTO']>(`${adminOffers}?limit=1&offset=1`, { token: owner })
    expect(page).toMatchObject({ total: 2, limit: 1, offset: 1, items: [{ id: current.id, status: 'archived' }] })
    await expectProblem(409, 'offer_not_editable', draftPath, { method: 'PATCH', token: owner, body: { title: 'Read-only' } })
    await expectProblem(409, 'offer_not_editable', `${draftPath}/publish`, { method: 'POST', token: owner })
    await expectProblem(409, 'offer_not_editable', `${adminOffers}/${current.id}`, { method: 'PATCH', token: owner, body: { title: 'Read-only' } })

    expect((await request<Schemas['Session']>(session, { token: rider })).json.offer_accepted).toBe(false)
    const nextBooking = { method: 'POST', token: rider, body: await bookingForDate(23) }
    await expectProblem(403, 'offer_not_accepted', '/rentals', nextBooking)
    await expectProblem(409, 'offer_not_active', acceptances, { method: 'POST', token: rider, body: { offer_version_id: current.id } })
    const accepted = await request<Schemas['OfferAcceptanceDTO']>(acceptances, {
      method: 'POST', token: rider, body: { offer_version_id: draft.json.id },
    })
    expect(accepted.response.status).toBe(200)
    expect((await request<Schemas['Session']>(session, { token: rider })).json.offer_accepted).toBe(true)
    const { json: history } = await request<Schemas['OfferAcceptanceDTO'][]>(acceptances, { token: rider })
    expect(history.map(item => item.offer_version_id)).toEqual([draft.json.id, current.id])
    expect((await request<Schemas['Rental']>('/rentals', nextBooking)).response.status).toBe(201)
  })
})
