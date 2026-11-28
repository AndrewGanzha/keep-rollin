import type { PushSubscriptionPayload, RegisteredPushSubscription } from '../api/notifications'

export type PushOperation = 'refresh' | 'enable' | 'disable'
export type PushStatus = 'checking' | 'off' | 'active' | 'denied' | 'install' | 'unsupported' | 'unconfigured' | 'session-changed' | 'error'

export interface PushEnrollment {
  account: string
  endpointHash: string
  enabled: boolean
}

interface SubscriptionDependencies {
  account: string
  action: PushOperation
  key: Uint8Array<ArrayBuffer>
  assertAccount: () => void
  enrollment: PushEnrollment | null
  saveEnrollment: (value: PushEnrollment | null) => void
  readBrowser: () => Promise<PushSubscription | null>
  subscribe: () => Promise<PushSubscription>
  unsubscribe: (subscription: PushSubscription) => Promise<void>
  list: () => Promise<RegisteredPushSubscription[]>
  register: (payload: PushSubscriptionPayload) => Promise<RegisteredPushSubscription>
  remove: (id: string) => Promise<void>
}

export const endpointFingerprint = async (endpoint: string) => {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(endpoint))
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('')
}

const serializeSubscription = (subscription: PushSubscription): PushSubscriptionPayload | null => {
  const { p256dh, auth } = subscription.toJSON().keys ?? {}
  const { endpoint, expirationTime } = subscription
  if (!endpoint || !p256dh || !auth || (expirationTime !== null && expirationTime <= Date.now())) return null
  return { endpoint, expirationTime, keys: { p256dh, auth } }
}

const usable = (subscription: PushSubscription, key: Uint8Array<ArrayBuffer>) => {
  const storedKey = subscription.options.applicationServerKey
  const bytes = storedKey ? new Uint8Array(storedKey) : null
  return bytes?.length === key.length && bytes.every((value, i) => value === key[i]) && !!serializeSubscription(subscription)
}

export const reconcilePushSubscription = async (deps: SubscriptionDependencies): Promise<'off' | 'active'> => {
  const { account, action, key, enrollment, assertAccount, saveEnrollment, unsubscribe, remove } = deps
  const local = await deps.readBrowser()
  const localHash = local && await endpointFingerprint(local.endpoint)
  const known = enrollment?.account === account ? enrollment : null
  const foreign = action === 'refresh' && !known ? enrollment : null
  assertAccount()

  if (!local && !known && !foreign && action !== 'enable') return 'off'
  const records = foreign && (!local || localHash === foreign.endpointHash) ? [] : await deps.list()
  assertAccount()
  const current = records.find(record => record.endpoint_hash === localHash)
  const enrolled = records.find(record => record.endpoint_hash === known?.endpointHash)

  // The browser is shared with a different account. Leave that account's server data to expire.
  if (foreign && !current) {
    if (local) {
      await unsubscribe(local)
      assertAccount()
    }
    saveEnrollment(null)
    return 'off'
  }

  if (action === 'disable' || (action === 'refresh' && known && !known.enabled)) {
    const record = action === 'disable' ? current ?? enrolled : enrolled
    const target = record?.endpoint_hash ?? known?.endpointHash
    if (!target) return 'off'

    saveEnrollment({ account, endpointHash: target, enabled: false })
    if (local && localHash === target) {
      await unsubscribe(local)
      assertAccount()
    }
    if (record) {
      await remove(record.id)
      assertAccount()
    }
    saveEnrollment(null)
    return 'off'
  }

  if (local && current && usable(local, key)) {
    saveEnrollment({ account, endpointHash: current.endpoint_hash, enabled: true })
    return 'active'
  }

  // Renew only an enrollment supported by the server or by this account's earlier opt-in.
  if (action === 'refresh' && !current && !known?.enabled) return 'off'

  if (current) saveEnrollment({ account, endpointHash: current.endpoint_hash, enabled: true })
  else if (action === 'enable' && enrollment && !known) saveEnrollment(null)
  const obsolete = current ?? enrolled
  if (obsolete) {
    await remove(obsolete.id)
    assertAccount()
  }
  if (local) {
    await unsubscribe(local)
    assertAccount()
  }

  const subscription = await deps.subscribe()
  try {
    const payload = serializeSubscription(subscription)
    const endpointHash = await endpointFingerprint(subscription.endpoint)
    assertAccount()
    if (!payload || endpointHash === localHash || endpointHash === known?.endpointHash) {
      throw new Error('Push subscription was not renewed')
    }
    const server = await deps.register(payload)
    assertAccount()
    if (server.endpoint_hash !== endpointHash) throw new Error('Push subscription was not confirmed')
    saveEnrollment({ account, endpointHash, enabled: true })
    return 'active'
  } catch (error) {
    await unsubscribe(subscription).catch(() => undefined)
    throw error
  }
}
