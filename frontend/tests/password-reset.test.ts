import { describe, expect, it, vi } from 'vitest'
import { requestPasswordReset, resetPassword } from '~/entities/session/api/session.api'
import { readPasswordResetToken } from '~/features/session/password/model/reset-token'
import { createApiClient } from '~/shared/api/client'

const token = 'valid-disposable-reset-token_123'

describe('password reset links', () => {
  it('reads a private fragment and supports an already-issued query link', () => {
    expect(readPasswordResetToken(null, `#token=${token}`)).toBe(token)
    expect(readPasswordResetToken(token, '')).toBe(token)
    expect(readPasswordResetToken('different-disposable-token', `#token=${token}`)).toBe(token)
  })

  it('rejects malformed or ambiguous links', () => {
    expect(readPasswordResetToken([token, token], '')).toBeNull()
    expect(readPasswordResetToken(null, `#token=${token}&token=${token}`)).toBeNull()
    expect(readPasswordResetToken(null, '#token=short')).toBeNull()
    expect(readPasswordResetToken(null, `#token=${token}%00`)).toBeNull()
  })
})

describe('password reset requests', () => {
  const apiFor = (response: Response) => {
    const fetch = vi.fn<typeof globalThis.fetch>().mockResolvedValue(response)
    return { api: createApiClient('http://localhost', () => null, undefined, fetch), fetch }
  }

  it('accepts the generic receipt without establishing a session', async () => {
    const { api, fetch } = apiFor(Response.json({ message: 'If the account exists…' }, { status: 202 }))
    await expect(requestPasswordReset(api, { email: 'rider@example.com' })).resolves.toBeUndefined()
    expect(fetch.mock.calls[0]?.[0].toString()).toBe('http://localhost/api/v1/auth/password/forgot')
  })

  it('sends the reset token in the request body and accepts an empty response', async () => {
    const { api, fetch } = apiFor(new Response(null, { status: 204 }))
    const body = { token, password: ' with spaces ' }
    await expect(resetPassword(api, body)).resolves.toBeUndefined()
    expect(fetch.mock.calls[0]?.[0].toString()).toBe('http://localhost/api/v1/auth/password/reset')
    expect(new TextDecoder().decode(fetch.mock.calls[0]?.[1]?.body as ArrayBuffer)).toBe(JSON.stringify(body))
  })

  it('preserves the error status for an expired or already spent token', async () => {
    const { api } = apiFor(Response.json({ code: 'token_invalid', title: 'Invalid token' }, { status: 401 }))
    await expect(resetPassword(api, { token, password: 'replacement-password' })).rejects.toMatchObject({
      code: 'token_invalid', status: 401,
    })
  })
})
