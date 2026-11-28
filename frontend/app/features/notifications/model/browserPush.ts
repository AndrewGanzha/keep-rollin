import type { PushEnrollment, PushStatus } from './pushSubscription'

export const pushWorker = '/notifications-sw.js'
export const enrollmentStorageKey = 'kr-push-enrollment'

// Open tabs may still have the previous session in memory after the shared login cookie changes.
export const browserSessionMatches = (cookies: string, token: string) => {
  const prefix = 'kr_token='
  const cookie = cookies.split(';').map(value => value.trim()).find(value => value.startsWith(prefix))
  if (!cookie) return false
  try {
    return decodeURIComponent(cookie.slice(prefix.length)) === token
  } catch {
    return false
  }
}

export const browserPushAvailability = (browser: Window & typeof globalThis): 'available' | PushStatus => {
  const { navigator } = browser
  const ios = /iPad|iPhone|iPod/.test(navigator.userAgent)
    || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
  const standalone = (navigator as Navigator & { standalone?: boolean }).standalone
    || browser.matchMedia('(display-mode: standalone)').matches
  if (ios && !standalone) return 'install'
  if (!browser.isSecureContext || !('serviceWorker' in navigator) || !('PushManager' in browser)
    || !('Notification' in browser) || !browser.crypto?.subtle) return 'unsupported'
  return 'available'
}

export const decodeVapidKey = (key: string | null | undefined) => {
  if (!key || !/^[\w-]+={0,2}$/.test(key)) return null
  try {
    const bytes = Uint8Array.from(atob(key.replace(/-/g, '+').replace(/_/g, '/')), char => char.charCodeAt(0))
    return bytes.length === 65 && bytes[0] === 4 ? bytes : null
  } catch {
    return null
  }
}

export const readPushEnrollment = (): PushEnrollment | null => {
  try {
    const value = JSON.parse(localStorage.getItem(enrollmentStorageKey) ?? 'null')
    if (value && typeof value.account === 'string' && typeof value.enabled === 'boolean'
      && typeof value.endpointHash === 'string' && /^[a-f\d]{64}$/.test(value.endpointHash)) {
      return value
    }
  } catch {
    // Some browsers block local storage. The server still confirms existing subscriptions.
  }
  return null
}

export const writePushEnrollment = (value: PushEnrollment | null) => {
  try {
    if (value) localStorage.setItem(enrollmentStorageKey, JSON.stringify(value))
    else localStorage.removeItem(enrollmentStorageKey)
  } catch {
    // Storage access is optional for explicit subscription management.
  }
}

const getPushRegistration = async () => {
  const registration = await navigator.serviceWorker.getRegistration('/')
  if (!registration) return null
  const worker = registration.active ?? registration.waiting ?? registration.installing
  if (worker?.scriptURL !== new URL(pushWorker, location.origin).href) {
    throw new Error('Unexpected service worker registration')
  }
  return registration
}

const waitForPushRegistration = async (registration: ServiceWorkerRegistration) => {
  if (registration.active?.state === 'activated') return registration

  let timeout: ReturnType<typeof setTimeout> | undefined
  try {
    return await Promise.race([
      navigator.serviceWorker.ready,
      new Promise<never>((_, reject) => {
        timeout = setTimeout(() => reject(new Error('Push service worker did not activate')), 8000)
      }),
    ])
  } finally {
    clearTimeout(timeout)
  }
}

export const createPushBrowser = (key: Uint8Array<ArrayBuffer>, assertAccount: () => void) => {
  let registration: ServiceWorkerRegistration | null = null

  return {
    async readBrowser() {
      registration = await getPushRegistration()
      return await registration?.pushManager.getSubscription() ?? null
    },
    async subscribe() {
      assertAccount()
      registration ??= await navigator.serviceWorker.register(pushWorker)
      registration = await waitForPushRegistration(registration)
      if (registration.active?.scriptURL !== new URL(pushWorker, location.origin).href) {
        throw new Error('Unexpected active service worker')
      }
      assertAccount()
      if (Notification.permission !== 'granted') throw new Error('Push permission changed')
      return await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key })
    },
    async unsubscribe(subscription: PushSubscription) {
      const removed = await subscription.unsubscribe()
      if (!removed && (await registration?.pushManager.getSubscription())?.endpoint === subscription.endpoint) {
        throw new Error('Push subscription is still present')
      }
    },
  }
}
