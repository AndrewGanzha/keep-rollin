import { describe, expect, it, vi } from 'vitest'
import type { NotificationPreferences, RegisteredPushSubscription } from '~/features/notifications/api/notifications'
import { browserPushAvailability, browserSessionMatches, createPushBrowser, decodeVapidKey } from '~/features/notifications/model/browserPush'
import { createNotificationPreferences } from '~/features/notifications/model/preferences'
import { endpointFingerprint, reconcilePushSubscription, type PushEnrollment } from '~/features/notifications/model/pushSubscription'

const defaultPreferences: NotificationPreferences = {
  push_enabled: true,
  email_by_event: { 'booking.confirmed': true, 'verification.rejected': true },
  locked_events: ['verification.rejected'],
}

describe('account notification preferences', () => {
  it('saves a partial change, prevents concurrent writes and rolls back an API 422', async () => {
    const response = Promise.withResolvers<NotificationPreferences>()
    const save = vi.fn(() => response.promise)
    const model = createNotificationPreferences(async () => defaultPreferences, save)
    await model.refresh()

    model.setEmail('verification.rejected', false)
    expect(save).not.toHaveBeenCalled()

    const updating = model.setEmail('booking.confirmed', false)
    expect(model.data.value?.email_by_event['booking.confirmed']).toBe(false)
    expect(model.saving.value).toBe(true)
    model.setPush(false)
    expect(save).toHaveBeenCalledExactlyOnceWith({ email_by_event: { 'booking.confirmed': false } })

    response.reject({ status: 422 })
    await updating
    expect(model.data.value).toEqual(defaultPreferences)
    expect(model.saving.value).toBe(false)
    expect(model.saveFailed.value).toBe(true)
  })

  it('loads shared state and ignores a response after the signed-in account is reset', async () => {
    const oldAccount = Promise.withResolvers<NotificationPreferences>()
    const newPreferences = { ...defaultPreferences, push_enabled: false }
    const load = vi.fn().mockReturnValueOnce(oldAccount.promise).mockResolvedValue(newPreferences)
    const save = vi.fn().mockResolvedValue(defaultPreferences)
    const model = createNotificationPreferences(load, save)
    const stale = model.refresh()
    model.reset()

    await model.refresh()
    oldAccount.resolve(defaultPreferences)
    await stale
    expect(model.data.value).toEqual(newPreferences)

    await model.setPush(true)
    expect(save).toHaveBeenCalledExactlyOnceWith({ push_enabled: true })
    expect(model.data.value).toEqual(defaultPreferences)
  })
})

const key = Uint8Array.from([4, ...new Array<number>(64).fill(5)])

const makeSubscription = (path: string, applicationServerKey = key) => {
  const endpoint = `https://push.example/${path}`
  return {
    endpoint,
    expirationTime: null,
    options: { userVisibleOnly: true, applicationServerKey: applicationServerKey.buffer },
    getKey: () => null,
    unsubscribe: async () => true,
    toJSON: () => ({ endpoint, keys: { auth: 'auth', p256dh: 'key' } }),
  } satisfies PushSubscription
}

const makeRecord = async (subscription: PushSubscription): Promise<RegisteredPushSubscription> => ({
  id: 'subscription-id',
  endpoint_hash: await endpointFingerprint(subscription.endpoint),
  expiration_time: null,
  user_agent: null,
  updated_at: '2026-01-01T00:00:00Z',
  created_at: '2026-01-01T00:00:00Z',
})

const makeDependencies = async (enrollment: PushEnrollment | null = null) => {
  const newSubscription = makeSubscription('fresh')
  const newRecord = await makeRecord(newSubscription)
  return {
    account: 'tenant/current-account',
    action: 'refresh' as const,
    key,
    assertAccount: vi.fn(),
    enrollment,
    saveEnrollment: vi.fn(),
    readBrowser: vi.fn<() => Promise<PushSubscription | null>>().mockResolvedValue(null),
    subscribe: vi.fn().mockResolvedValue(newSubscription),
    unsubscribe: vi.fn().mockResolvedValue(undefined),
    list: vi.fn<() => Promise<RegisteredPushSubscription[]>>().mockResolvedValue([]),
    register: vi.fn().mockResolvedValue(newRecord),
    remove: vi.fn().mockResolvedValue(undefined),
    newSubscription,
    newRecord,
  }
}

describe('browser push enrollment', () => {
  it('requires explicit enable for a fresh browser and only confirms a registered endpoint', async () => {
    const deps = await makeDependencies()
    expect(await reconcilePushSubscription(deps)).toBe('off')
    expect(deps.subscribe).not.toHaveBeenCalled()

    expect(await reconcilePushSubscription({ ...deps, action: 'enable' })).toBe('active')
    expect(deps.register).toHaveBeenCalledExactlyOnceWith({
      endpoint: deps.newSubscription.endpoint,
      expirationTime: null,
      keys: { auth: 'auth', p256dh: 'key' },
    })
    expect(deps.saveEnrollment).toHaveBeenCalledExactlyOnceWith({
      account: deps.account, endpointHash: deps.newRecord.endpoint_hash, enabled: true,
    })

    deps.readBrowser.mockResolvedValue(deps.newSubscription)
    deps.list.mockResolvedValue([deps.newRecord])
    expect(await reconcilePushSubscription(deps)).toBe('active')
    expect(deps.subscribe).toHaveBeenCalledOnce()
  })

  it.each(['invalidated', 'rotated in browser', 'rotated VAPID key'])('repairs a known %s subscription with a new endpoint', async (reason) => {
    const old = makeSubscription('old', reason === 'rotated VAPID key' ? Uint8Array.of(1) : key)
    const record = await makeRecord(old)
    const deps = await makeDependencies({ account: 'tenant/current-account', endpointHash: record.endpoint_hash, enabled: true })
    const local = reason === 'rotated in browser' ? makeSubscription('browser-rotated') : old
    deps.readBrowser.mockResolvedValue(local)
    deps.list.mockResolvedValue(reason === 'invalidated' ? [] : [record])

    expect(await reconcilePushSubscription(deps)).toBe('active')
    expect(deps.unsubscribe).toHaveBeenCalledExactlyOnceWith(local)
    expect(deps.remove).toHaveBeenCalledTimes(reason === 'invalidated' ? 0 : 1)
    expect(deps.register).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({ endpoint: deps.newSubscription.endpoint }))
  })

  it('never claims another account’s local endpoint and explicit takeover creates a new one', async () => {
    const foreign = makeSubscription('foreign')
    const foreignRecord = await makeRecord(foreign)
    const deps = await makeDependencies({ account: 'tenant/foreign-account', endpointHash: foreignRecord.endpoint_hash, enabled: true })
    deps.readBrowser.mockResolvedValue(foreign)

    expect(await reconcilePushSubscription(deps)).toBe('off')
    expect(deps.unsubscribe).toHaveBeenCalledExactlyOnceWith(foreign)
    expect(deps.saveEnrollment).toHaveBeenCalledExactlyOnceWith(null)
    expect(deps.list).not.toHaveBeenCalled()
    expect(deps.register).not.toHaveBeenCalled()

    deps.unsubscribe.mockClear()
    expect(await reconcilePushSubscription({ ...deps, action: 'enable' })).toBe('active')
    expect(deps.remove).not.toHaveBeenCalled()
    expect(deps.unsubscribe).toHaveBeenCalledExactlyOnceWith(foreign)
    expect(deps.register).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({ endpoint: deps.newSubscription.endpoint }))
  })

  it.each([false, true])('checks ownership when the endpoint differs from another account’s marker (confirmed: %s)', async (confirmed) => {
    const old = await makeRecord(makeSubscription('old'))
    const deps = await makeDependencies({ account: 'tenant/foreign-account', endpointHash: old.endpoint_hash, enabled: true })
    deps.readBrowser.mockResolvedValue(deps.newSubscription)
    if (confirmed) deps.list.mockResolvedValue([deps.newRecord])

    expect(await reconcilePushSubscription(deps)).toBe(confirmed ? 'active' : 'off')
    expect(deps.list).toHaveBeenCalledOnce()
    expect(deps.unsubscribe).toHaveBeenCalledTimes(confirmed ? 0 : 1)
    expect(deps.register).not.toHaveBeenCalled()
    expect(deps.remove).not.toHaveBeenCalled()
  })

  it('recognizes when a different tab replaced the login cookie', () => {
    const cookies = 'kr_theme=light; kr_token=mock%3Anew-account; other=session'
    expect(browserSessionMatches(cookies, 'mock:old-account')).toBe(false)
    expect(browserSessionMatches(cookies, 'mock:new-account')).toBe(true)
    expect(browserSessionMatches('kr_theme=light', 'mock:old-account')).toBe(false)
  })

  it('does not ask the push manager to subscribe if browser permission is no longer granted', async () => {
    const subscribe = vi.fn()
    vi.stubGlobal('location', { origin: 'https://example.test' })
    vi.stubGlobal('Notification', { permission: 'default' })
    vi.stubGlobal('navigator', {
      serviceWorker: {
        register: async () => ({
          active: { state: 'activated', scriptURL: 'https://example.test/notifications-sw.js' },
          pushManager: { subscribe },
        }),
      },
    })
    try {
      await expect(createPushBrowser(key, vi.fn()).subscribe()).rejects.toThrow('Push permission changed')
      expect(subscribe).not.toHaveBeenCalled()
    } finally {
      vi.unstubAllGlobals()
    }
  })

  it('stops before registering when the account changes during subscribe', async () => {
    const deps = await makeDependencies()
    let current = true
    deps.assertAccount.mockImplementation(() => {
      if (!current) throw new Error('changed account')
    })
    deps.subscribe.mockImplementation(async () => {
      current = false
      return deps.newSubscription
    })

    await expect(reconcilePushSubscription({ ...deps, action: 'enable' })).rejects.toThrow('changed account')
    expect(deps.register).not.toHaveBeenCalled()
    expect(deps.unsubscribe).toHaveBeenCalledExactlyOnceWith(deps.newSubscription)
  })

  it('cleans up a browser endpoint when its API registration fails', async () => {
    const deps = await makeDependencies()
    deps.register.mockRejectedValue(new Error('Registration failed'))

    await expect(reconcilePushSubscription({ ...deps, action: 'enable' })).rejects.toThrow('Registration failed')
    expect(deps.saveEnrollment).not.toHaveBeenCalled()
    expect(deps.unsubscribe).toHaveBeenCalledExactlyOnceWith(deps.newSubscription)
  })

  it('disables a local subscription and retries deletion without re-subscribing after a server error', async () => {
    const subscription = makeSubscription('old')
    const record = await makeRecord(subscription)
    const deps = await makeDependencies()
    deps.readBrowser.mockResolvedValueOnce(subscription)
    deps.list.mockResolvedValue([record])
    deps.remove.mockRejectedValueOnce(new Error('Server unavailable'))

    await expect(reconcilePushSubscription({ ...deps, action: 'disable' })).rejects.toThrow('Server unavailable')
    const optOut = { account: deps.account, endpointHash: record.endpoint_hash, enabled: false }
    expect(deps.saveEnrollment).toHaveBeenCalledWith(optOut)
    expect(deps.unsubscribe).toHaveBeenCalledExactlyOnceWith(subscription)

    expect(await reconcilePushSubscription({ ...deps, enrollment: optOut })).toBe('off')
    expect(deps.remove).toHaveBeenNthCalledWith(2, record.id)
    expect(deps.subscribe).not.toHaveBeenCalled()
    expect(deps.saveEnrollment).toHaveBeenLastCalledWith(null)
  })

  it('shows iOS install help before unavailable browser capability and validates the VAPID key format', () => {
    const ios = {
      navigator: { userAgent: 'iPhone', platform: 'iPhone', maxTouchPoints: 5 },
      matchMedia: () => ({ matches: false }),
      isSecureContext: true,
    } as unknown as Window & typeof globalThis
    expect(browserPushAvailability(ios)).toBe('install')
    expect(browserPushAvailability({ ...ios, matchMedia: () => ({ matches: true }) } as typeof ios)).toBe('unsupported')
    expect(decodeVapidKey('invalid')).toBeNull()
    expect(decodeVapidKey(Buffer.from(key).toString('base64url'))).toEqual(key)
  })
})
