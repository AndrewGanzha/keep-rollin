import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'
import { describe, expect, it, vi } from 'vitest'

const origin = 'https://keep-rollin.test'
const publicDirectory = new URL('../public/', import.meta.url)
const workerScript = readFileSync(new URL('notifications-sw.js', publicDirectory), 'utf8')

function windowClient(url: string, frameType = 'top-level') {
  const client = { url, frameType, focus: vi.fn(), navigate: vi.fn(), postMessage: vi.fn() }
  client.focus.mockResolvedValue(client)
  client.navigate.mockResolvedValue(client)
  return client
}

type WorkerEvent = {
  waitUntil: (work: Promise<unknown>) => void
  data?: { json: () => unknown }
  notification?: { data?: { url?: unknown }; close: () => void }
}

function setupWorker(windows: ReturnType<typeof windowClient>[] = []) {
  const handlers = new Map<string, (event: WorkerEvent) => void>()
  const clients = {
    claim: vi.fn().mockResolvedValue(undefined),
    matchAll: vi.fn().mockResolvedValue(windows),
    openWindow: vi.fn().mockResolvedValue(null),
  }
  const showNotification = vi.fn().mockResolvedValue(undefined)
  runInNewContext(workerScript, {
    URL,
    self: {
      location: { origin },
      clients,
      registration: { showNotification },
      addEventListener: (type: string, handler: (event: WorkerEvent) => void) => handlers.set(type, handler),
    },
  })

  async function dispatch(type: string, details: Omit<WorkerEvent, 'waitUntil'> = {}) {
    const handler = handlers.get(type)
    if (!handler) throw new Error(`Missing worker listener for ${type}`)
    const waitUntil = vi.fn<WorkerEvent['waitUntil']>()
    handler({ ...details, waitUntil })
    expect(waitUntil).toHaveBeenCalledTimes(1)
    await waitUntil.mock.calls[0][0]
  }

  return { clients, showNotification, dispatch }
}

describe('browser notification service worker', () => {
  it('claims existing pages as soon as the worker activates', async () => {
    const { clients, dispatch } = setupWorker()
    await dispatch('activate')
    expect(clients.claim).toHaveBeenCalledOnce()
  })

  it.each([
    '/account/rentals',
    '/account/tickets',
    '/account/verification',
    '/admin/rentals',
    '/admin/tickets',
  ])('displays the push payload and opens %s', async (url) => {
    const { clients, showNotification, dispatch } = setupWorker()
    const payload = { title: 'Уведомление', body: 'Подробнее в кабинете', url, tag: 'outbox-id' }
    await dispatch('push', { data: { json: () => payload } })
    expect(showNotification).toHaveBeenCalledWith(payload.title, {
      body: payload.body, icon: '/icons/app-192.png', tag: payload.tag, data: { url },
    })

    const close = vi.fn()
    await dispatch('notificationclick', { notification: { ...showNotification.mock.calls[0][1], close } })
    expect(close).toHaveBeenCalledOnce()
    expect(clients.openWindow).toHaveBeenCalledWith(`${origin}${url}`)
  })

  it('shows the generic notification when the push data is malformed', async () => {
    const { showNotification, dispatch } = setupWorker()
    await dispatch('push', { data: { json: () => { throw new SyntaxError('invalid JSON') } } })
    expect(showNotification).toHaveBeenCalledWith('Keep Rollin', expect.objectContaining({
      body: 'У вас новое уведомление.',
      data: { url: '/' },
    }))
  })

  it.each([
    'https://elsewhere.test/account/rentals',
    `${origin}/account/rentals`,
    '//elsewhere.test/account/rentals',
    '/account/rentals?next=elsewhere',
    '/account/rentals#details',
    '/account//rentals',
    '/account/../admin/tickets',
    '/account/rentals/',
    '/admin',
    undefined,
  ])('falls back to the app home for an unapproved URL (%s)', async (url) => {
    const { clients, showNotification, dispatch } = setupWorker()
    await dispatch('push', { data: { json: () => ({ title: 'Уведомление', url }) } })
    expect(showNotification).toHaveBeenCalledWith('Уведомление', expect.objectContaining({ data: { url: '/' } }))

    await dispatch('notificationclick', { notification: { data: { url }, close: vi.fn() } })
    expect(clients.openWindow).toHaveBeenCalledWith(`${origin}/`)
  })

  it('focuses the matching top-level window and corrects stale SPA routing', async () => {
    const url = '/account/rentals'
    const embedded = windowClient(`${origin}${url}`, 'nested')
    const matching = windowClient(`${origin}${url}`)
    const unrelated = windowClient(`${origin}/account/tickets`)
    const { clients, dispatch } = setupWorker([unrelated, embedded, matching])
    await dispatch('notificationclick', { notification: { data: { url }, close: vi.fn() } })
    expect(matching.focus).toHaveBeenCalledOnce()
    expect(matching.navigate).toHaveBeenCalledWith(`${origin}${url}`)
    expect(unrelated.focus).not.toHaveBeenCalled()
    expect(embedded.focus).not.toHaveBeenCalled()
    expect(clients.openWindow).not.toHaveBeenCalled()
  })

  it('reuses the notification tab after signing in and navigating to the target in the SPA', async () => {
    const url = '/account/verification'
    const unrelated = windowClient(`${origin}/account/rentals`)
    const signedInTab = windowClient(`${origin}/login?next=${encodeURIComponent(url)}`)
    const { clients, dispatch } = setupWorker([unrelated, signedInTab])
    await dispatch('notificationclick', { notification: { data: { url }, close: vi.fn() } })
    expect(signedInTab.focus).toHaveBeenCalledOnce()
    expect(signedInTab.navigate).toHaveBeenCalledWith(`${origin}${url}`)
    expect(unrelated.focus).not.toHaveBeenCalled()
    expect(clients.openWindow).not.toHaveBeenCalled()
  })

  it('reuses the most recently focused app window when only a different creation URL is available', async () => {
    const url = '/account/tickets'
    const existing = windowClient(`${origin}/`)
    const { clients, dispatch } = setupWorker([existing])
    await dispatch('notificationclick', { notification: { data: { url }, close: vi.fn() } })
    expect(existing.focus).toHaveBeenCalledOnce()
    expect(existing.navigate).toHaveBeenCalledWith(`${origin}${url}`)
    expect(clients.openWindow).not.toHaveBeenCalled()
  })

  it('opens the destination if the matching tab closes before it can be focused', async () => {
    const url = '/admin/tickets'
    const matching = windowClient(`${origin}${url}`)
    matching.focus.mockRejectedValue(new TypeError('window closed'))
    const { clients, dispatch } = setupWorker([matching])
    await dispatch('notificationclick', { notification: { data: { url }, close: vi.fn() } })
    expect(clients.openWindow).toHaveBeenCalledWith(`${origin}${url}`)
  })

  it('sends only the renewal signal to same-origin app windows, including the first load', async () => {
    const matching = windowClient(`${origin}/account/rentals`)
    const otherMatching = windowClient(`${origin}/account/tickets`)
    const external = windowClient(`${origin}.external.test/account/rentals`)
    const embedded = windowClient(`${origin}/account/rentals`, 'nested')
    const { clients, dispatch } = setupWorker([matching, otherMatching, external, embedded])
    await dispatch('pushsubscriptionchange')
    expect(clients.matchAll).toHaveBeenCalledWith({ type: 'window', includeUncontrolled: true })
    expect(matching.postMessage).toHaveBeenCalledExactlyOnceWith({ type: 'pushsubscriptionchange' })
    expect(otherMatching.postMessage).toHaveBeenCalledExactlyOnceWith({ type: 'pushsubscriptionchange' })
    expect(external.postMessage).not.toHaveBeenCalled()
    expect(embedded.postMessage).not.toHaveBeenCalled()
  })

  it('serves a standalone manifest with correctly sized local PNG icons', () => {
    const manifest = JSON.parse(readFileSync(new URL('manifest.webmanifest', publicDirectory), 'utf8'))
    expect(manifest).toMatchObject({ id: '/', start_url: '/', display: 'standalone', scope: '/' })
    for (const size of [192, 512]) {
      const src = `/icons/app-${size}.png`
      expect(manifest.icons).toContainEqual({ src, sizes: `${size}x${size}`, type: 'image/png' })
      const png = readFileSync(new URL(src.slice(1), publicDirectory))
      expect(png.subarray(0, 8)).toEqual(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))
      expect([png.readUInt32BE(16), png.readUInt32BE(20)]).toEqual([size, size])
    }
  })
})
