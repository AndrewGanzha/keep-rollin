import { describe, expect, it, vi } from 'vitest'
import contract from '../../contract/openapi.json'
import { acceptOffer, fetchCurrentOffer } from '~/entities/offer/api/offer.api'
import { renderOfferMarkdown } from '~/entities/offer/model/markdown'
import { offerGateLocation } from '~/features/offer-acceptance/model/offer-return'
import { loginCredentials, registrationCredentials } from '~/features/session/model/credentials'
import { createApiClient } from '~/shared/api/client'

describe('credentials submitted to FastAPI', () => {
  const limits = contract.components.schemas.RegisterRequest.properties
  const base = { email: '  RIDER@example.test  ', password: ' abcdef ', name: '', phone: '' }

  it('normalizes email and removes optional empty fields while preserving password spaces', () => {
    expect(registrationCredentials.parse(base)).toEqual({
      email: 'rider@example.test', password: ' abcdef ', name: undefined, phone: undefined,
    })
  })

  it('accepts the exact Unicode length bounds and rejects out-of-range values', () => {
    const password = '🚲'.repeat(limits.password.maxLength)
    expect(registrationCredentials.safeParse({ ...base, password }).success).toBe(true)
    expect(registrationCredentials.safeParse({ ...base, password: password + 'x' }).success).toBe(false)
    expect(loginCredentials.safeParse({ ...base, password: 'x'.repeat(limits.password.minLength - 1) }).success).toBe(false)
    expect(registrationCredentials.safeParse({ ...base, name: 'я'.repeat(limits.name.anyOf[0]!.maxLength! + 1) }).success).toBe(false)
    expect(registrationCredentials.safeParse({ ...base, phone: '0'.repeat(limits.phone.anyOf[0]!.maxLength! + 1) }).success).toBe(false)
  })

  it('checks email shape and rejects NUL characters', () => {
    expect(loginCredentials.safeParse({ ...base, email: 'rider@example' }).success).toBe(false)
    expect(loginCredentials.safeParse({ ...base, password: 'test\0password' }).success).toBe(false)
  })
})

describe('rendered offer', () => {
  it('renders headings and formatting but never loads remote images or creates executable HTML', () => {
    const source = '# Draft\n\n**Terms**\n\n<script>ignored</script>\n\n![asset](https://example.test/image.png)\n\n[unsafe](javascript:alert(1))'
    const rendered = renderOfferMarkdown(source)
    expect(rendered).toContain('<h1>Draft</h1>')
    expect(rendered).toContain('<strong>Terms</strong>')
    expect(rendered).not.toContain('<script>')
    expect(rendered).not.toContain('<img')
    expect(rendered).not.toContain('href="javascript:')
  })
})

describe('offer acceptance', () => {
  it('round trips booking return paths and falls back for redirects or loops', () => {
    expect(offerGateLocation('/lots/cargo?days=7#prices').query.next).toBe('/lots/cargo?days=7#prices')
    for (const target of ['//example.test', '/\\example.test', '/\n/example.test', '/account/offer/?next=//example.test']) {
      expect(offerGateLocation(target).query.next).toBe('/account/verification')
    }
  })

  it('fetches fresh wording and submits exactly the version shown', async () => {
    const version = '00000000-0000-4000-8000-000000000011'
    const received: Request[] = []
    const mockFetch = vi.fn<typeof fetch>().mockImplementation(async (url, init) => {
      const request = new Request(url, init)
      received.push(request)
      return Response.json({ id: version })
    })
    const api = createApiClient('http://tenant.example.test', () => 'test-session', undefined, mockFetch)
    const shown = await fetchCurrentOffer(api)
    await acceptOffer(api, shown.id)
    expect(received[0]?.headers.get('cache-control')).toBe('no-cache')
    expect(await received[1]?.json()).toEqual({ offer_version_id: version })
  })
})
