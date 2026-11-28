import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, ref, type EffectScope } from 'vue'
import { useLogin } from '~/features/session/login/model/useLogin'
import { ApiError } from '~/shared/api'

const requests = vi.hoisted(() => ({
  loginRequest: vi.fn(),
  setupMfa: vi.fn(),
  confirmMfa: vi.fn(),
  verifyMfa: vi.fn(),
  fetchSession: vi.fn(),
  useSessionStore: vi.fn(),
}))

vi.mock('~/entities/session', () => requests)
vi.mock('~/shared/api', async (original) => ({
  ...await original<object>(),
  useApi: () => api,
}))

const api = {}
const navigate = vi.fn()
const useCookie = vi.fn(() => cookie)
const useRequestURL = vi.fn()
const auth = { access_token: 'access-token', expires_in: 900 }
const challenge = { mfa_required: true, mfa_token: 'verify-challenge' }
const enrollment = { mfa_setup_required: true, mfa_token: 'setup-challenge' }
const setupDetails = { secret: 'TESTKEY', otpauth_uri: 'otpauth://totp/test?secret=TESTKEY' }
const recoveryCodes = ['0000-0000-0000-0000-0001', '0000-0000-0000-0000-0002']

let scope: EffectScope
let cookie: ReturnType<typeof ref<string | null>>
let route: { query: { next?: string } }
let session: { role: string } | null

beforeEach(() => {
  vi.resetAllMocks()
  scope = effectScope()
  cookie = ref<string | null>(null)
  route = { query: {} }
  session = null

  useCookie.mockImplementation(() => cookie)
  useRequestURL.mockReturnValue(new URL('http://localhost'))
  vi.stubGlobal('useCookie', useCookie)
  vi.stubGlobal('useRequestURL', useRequestURL)
  vi.stubGlobal('useState', (_key: string, initialize: () => unknown) => ref(initialize()))
  vi.stubGlobal('useRoute', () => route)
  vi.stubGlobal('navigateTo', navigate)

  requests.fetchSession.mockResolvedValue({ role: 'owner' })
  requests.useSessionStore.mockReturnValue({
    get isAuthenticated() { return session !== null },
    get isStaff() { return session?.role === 'admin' || session?.role === 'owner' },
    setSession: (value: { role: string }) => { session = value },
    clear: () => { session = null },
  })
})

afterEach(() => {
  scope.stop()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  vi.useRealTimers()
})

const loginFlow = () => scope.run(useLogin)!
const submitCredentials = (flow: ReturnType<typeof useLogin>) => flow.submit('staff@example.test', 'test-password')

describe('staff two-factor sign-in', () => {
  it.each(['123456', recoveryCodes[0]!])('establishes a session only after verifying %s', async (code) => {
    requests.loginRequest.mockResolvedValue({ ...challenge, access_token: 'ignore-during-challenge' })
    requests.verifyMfa.mockResolvedValue(auth)
    const flow = loginFlow()

    await submitCredentials(flow)
    expect(flow.stage.value).toBe('verify')
    expect(cookie.value).toBeNull()
    expect(requests.fetchSession).not.toHaveBeenCalled()
    expect(navigate).not.toHaveBeenCalled()

    await flow.submitCode(' ' + code + ' ')
    expect(requests.verifyMfa).toHaveBeenCalledExactlyOnceWith(api, { mfa_token: challenge.mfa_token, code })
    expect(cookie.value).toBe(auth.access_token)
    expect(requests.fetchSession).toHaveBeenCalledOnce()
    expect(navigate).toHaveBeenCalledExactlyOnceWith('/admin')
  })

  it('loads enrollment details, confirms once and downloads recovery codes once before continuing', async () => {
    vi.useFakeTimers()
    requests.loginRequest.mockResolvedValue(enrollment)
    requests.setupMfa.mockResolvedValue(setupDetails)
    const confirmation = Promise.withResolvers<typeof auth & { recovery_codes: string[] }>()
    requests.confirmMfa.mockReturnValue(confirmation.promise)
    const click = vi.fn()
    const link = { href: '', download: '', click }
    vi.stubGlobal('document', { createElement: vi.fn(() => link) })
    const createObjectURL = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:recovery')
    const revokeObjectURL = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
    const flow = loginFlow()

    await submitCredentials(flow)
    expect(flow.stage.value).toBe('setup')
    expect(flow.setup.value).toEqual(setupDetails)
    expect(requests.setupMfa).toHaveBeenCalledExactlyOnceWith(api, { mfa_token: enrollment.mfa_token })
    expect(cookie.value).toBeNull()

    await flow.submitCode(recoveryCodes[0]!)
    expect(requests.confirmMfa).not.toHaveBeenCalled()
    const confirming = flow.submitCode('123456')
    await flow.submitCode('123456')
    expect(requests.confirmMfa).toHaveBeenCalledExactlyOnceWith(api, { mfa_token: enrollment.mfa_token, code: '123456' })
    confirmation.resolve({ ...auth, recovery_codes: recoveryCodes })
    await confirming

    expect(flow.stage.value).toBe('recovery')
    expect(flow.recovery.value?.codes).toEqual(recoveryCodes)
    expect(flow.setup.value).toBeUndefined()
    expect(cookie.value).toBeNull()
    expect(requests.fetchSession).not.toHaveBeenCalled()
    expect(navigate).not.toHaveBeenCalled()

    flow.downloadRecoveryCodes()
    flow.downloadRecoveryCodes()
    expect(flow.recovery.value?.downloaded).toBe(true)
    expect(click).toHaveBeenCalledOnce()
    expect(link.download).toBe('keep-rollin-recovery-codes.txt')
    expect(createObjectURL).toHaveBeenCalledOnce()
    expect(await createObjectURL.mock.calls[0]?.[0].text()).toBe(recoveryCodes.join('\n') + '\n')
    vi.runOnlyPendingTimers()
    expect(revokeObjectURL).toHaveBeenCalledExactlyOnceWith('blob:recovery')

    await flow.continueAfterRecovery()
    expect(cookie.value).toBe(auth.access_token)
    expect(requests.fetchSession).toHaveBeenCalledOnce()
    expect(navigate).toHaveBeenCalledExactlyOnceWith('/admin')
    expect(flow.recovery.value).toBeUndefined()
  })

  it('retains the recovery screen when finishing enrollment cannot load the session', async () => {
    requests.loginRequest.mockResolvedValue(enrollment)
    requests.setupMfa.mockResolvedValue(setupDetails)
    requests.confirmMfa.mockResolvedValue({ ...auth, recovery_codes: recoveryCodes })
    requests.fetchSession.mockRejectedValueOnce(new Error('Network'))
    const flow = loginFlow()

    await submitCredentials(flow)
    await flow.submitCode('123456')
    await flow.continueAfterRecovery()
    expect(cookie.value).toBeNull()
    expect(flow.recovery.value?.codes).toEqual(recoveryCodes)
    expect(navigate).not.toHaveBeenCalled()

    await flow.continueAfterRecovery()
    expect(cookie.value).toBe(auth.access_token)
    expect(requests.confirmMfa).toHaveBeenCalledOnce()
    expect(navigate).toHaveBeenCalledExactlyOnceWith('/admin')
    expect(flow.recovery.value).toBeUndefined()
  })

  it('allows a manual retry when enrollment setup fails', async () => {
    requests.loginRequest.mockResolvedValue(enrollment)
    requests.setupMfa.mockRejectedValueOnce(new Error('Network')).mockResolvedValue(setupDetails)
    const flow = loginFlow()

    await submitCredentials(flow)
    expect(flow.stage.value).toBe('setup')
    expect(flow.setup.value).toBeUndefined()
    expect(requests.setupMfa).toHaveBeenCalledTimes(1)
    expect(cookie.value).toBeNull()

    await flow.requestSetup()
    expect(flow.setup.value).toEqual(setupDetails)
    expect(requests.setupMfa).toHaveBeenCalledTimes(2)
  })

  it('lets users retry an invalid code, pauses for Retry-After and returns to login on expiry', async () => {
    vi.useFakeTimers()
    requests.loginRequest.mockResolvedValue(challenge)
    requests.verifyMfa
      .mockRejectedValueOnce(new ApiError({ code: 'invalid_mfa_code', detail: 'sensitive detail' }, 401))
      .mockRejectedValueOnce(new ApiError({ code: 'rate_limited' }, 429, 3))
      .mockRejectedValueOnce(new ApiError({ code: 'token_expired' }, 401))
    const flow = loginFlow()

    await submitCredentials(flow)
    await flow.submitCode('123456')
    expect(flow.stage.value).toBe('verify')
    expect(flow.errorText.value).toMatch(/Код неверен/)
    expect(flow.errorText.value).not.toContain('sensitive detail')
    await flow.submitCode('123456')
    expect(flow.retryAfter.value).toBe(3)
    await flow.submitCode('123456')
    expect(requests.verifyMfa).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(3000)
    expect(flow.retryAfter.value).toBe(0)
    await flow.submitCode('123456')

    expect(flow.stage.value).toBe('credentials')
    expect(flow.errorText.value).toMatch(/Введите email и пароль снова/)
    expect(cookie.value).toBeNull()
  })

  it('discards an unfinished response when login leaves the component scope', async () => {
    requests.loginRequest.mockResolvedValue(challenge)
    const verification = Promise.withResolvers<typeof auth>()
    requests.verifyMfa.mockReturnValue(verification.promise)
    const flow = loginFlow()
    await submitCredentials(flow)
    const pending = flow.submitCode('123456')
    scope.stop()
    verification.resolve(auth)
    await pending

    expect(flow.stage.value).toBe('credentials')
    expect(cookie.value).toBeNull()
    expect(navigate).not.toHaveBeenCalled()
  })
})

describe('direct sign-in', () => {
  it.each([
    ['https://rental.example.test', true],
    ['http://localhost', false],
  ])('sets cookie security for %s', (origin, secure) => {
    useRequestURL.mockReturnValue(new URL(origin))
    loginFlow()
    expect(useRequestURL).toHaveBeenCalledExactlyOnceWith({ xForwardedProto: true })
    expect(useCookie).toHaveBeenCalledExactlyOnceWith('kr_token', expect.objectContaining({ secure }))
  })

  it.each([
    ['/account/tickets?status=open#list', '/account/tickets?status=open#list'],
    [undefined, '/account/rentals'],
    ['//elsewhere.test', '/account/rentals'],
    ['/\\elsewhere.test', '/account/rentals'],
    ['/\t/elsewhere.test', '/account/rentals'],
    ['/.//elsewhere.test', '/account/rentals'],
    ['https://elsewhere.test', '/account/rentals'],
  ])('chooses an app-local destination for next=%s', async (next, expected) => {
    route.query.next = next
    requests.loginRequest.mockResolvedValue(auth)
    requests.fetchSession.mockResolvedValue({ role: 'user' })
    const flow = loginFlow()

    await submitCredentials(flow)

    expect(cookie.value).toBe(auth.access_token)
    expect(requests.setupMfa).not.toHaveBeenCalled()
    expect(navigate).toHaveBeenCalledExactlyOnceWith(expected)
  })

  it('clears a token when the server does not establish a session', async () => {
    requests.loginRequest.mockResolvedValue(auth)
    requests.fetchSession.mockRejectedValue(new ApiError({ code: 'token_invalid' }, 401))
    const flow = loginFlow()
    await submitCredentials(flow)

    expect(cookie.value).toBeNull()
    expect(flow.errorText.value).toMatch(/Не удалось завершить вход/)
    expect(navigate).not.toHaveBeenCalled()
  })
})
