import { useSessionStore } from '~/entities/session'
import { useTenant } from '~/entities/tenant'
import { ApiError, useApi } from '~/shared/api'
import { deletePushSubscription, listPushSubscriptions, registerPushSubscription } from '../api/notifications'
import { browserPushAvailability, browserSessionMatches, createPushBrowser, decodeVapidKey, enrollmentStorageKey, pushWorker, readPushEnrollment, writePushEnrollment } from './browserPush'
import { reconcilePushSubscription, type PushOperation, type PushStatus } from './pushSubscription'

export const useBrowserPush = () => {
  const api = useApi()
  const session = useSessionStore()
  const tenant = useTenant()
  const token = useState<string | null>('access-token')
  const account = computed(() => session.user ? `${tenant.value?.id ?? ''}/${session.user.id}` : null)
  const storedStatus = useState<PushStatus>('browser-push-status', () => 'checking')
  const statusAccount = useState<string | null>('browser-push-status-account', () => null)
  const busy = useState('browser-push-busy', () => false)
  const refreshPending = useState('browser-push-refresh-pending', () => false)
  const failedAction = useState<PushOperation>('browser-push-failed-action', () => 'refresh')
  const operationError = useState<string | null>('browser-push-operation-error', () => null)
  const status = computed(() => statusAccount.value === account.value ? storedStatus.value : 'checking')

  const operate = async (action: PushOperation) => {
    if (!import.meta.client || !account.value || !token.value) return
    if (busy.value) {
      if (action === 'refresh') refreshPending.value = true
      return
    }

    const actor = account.value
    const accessToken = token.value
    const sameTabAccount = () => account.value === actor && token.value === accessToken
    const sameAccount = () => sameTabAccount() && browserSessionMatches(document.cookie, accessToken)
    const assertAccount = () => {
      if (!sameAccount()) throw new Error('The signed-in account changed')
    }
    busy.value = true
    if (action !== 'enable' || statusAccount.value !== actor) storedStatus.value = 'checking'
    statusAccount.value = actor
    operationError.value = null

    try {
      assertAccount()
      const availability = browserPushAvailability(window)
      if (availability !== 'available') {
        storedStatus.value = availability
        return
      }
      const key = decodeVapidKey(tenant.value?.vapid_public_key)
      if (!key) {
        storedStatus.value = 'unconfigured'
        return
      }

      // Call from the click handler before waiting for the browser lock or an API request.
      const permission = action === 'enable' && Notification.permission === 'default'
        ? await Notification.requestPermission()
        : Notification.permission
      assertAccount()
      if (permission !== 'granted' && action !== 'disable') {
        storedStatus.value = permission === 'denied' ? 'denied' : 'off'
        return
      }

      const reconcile = async () => {
        assertAccount()
        if (action !== 'disable' && Notification.permission !== 'granted') return 'off' as const
        return await reconcilePushSubscription({
          ...createPushBrowser(key, assertAccount),
          account: actor,
          action,
          key,
          assertAccount,
          enrollment: readPushEnrollment(),
          saveEnrollment: writePushEnrollment,
          list: () => listPushSubscriptions(api),
          register: payload => registerPushSubscription(api, payload),
          remove: id => deletePushSubscription(api, id),
        })
      }

      const received = navigator.locks ? await navigator.locks.request(enrollmentStorageKey, reconcile) : await reconcile()
      assertAccount()
      storedStatus.value = Notification.permission === 'denied' ? 'denied'
        : Notification.permission === 'granted' ? received : 'off'
    } catch (error) {
      if (sameAccount()) {
        storedStatus.value = 'error'
        failedAction.value = action
        operationError.value = action === 'enable' && error instanceof ApiError && error.status === 409
          ? 'Не удалось зарегистрировать подписку. Возможно, достигнут лимит устройств или браузер уже подключён к другому аккаунту.'
          : null
      } else if (sameTabAccount()) {
        storedStatus.value = 'session-changed'
      }
    } finally {
      busy.value = false
      if (refreshPending.value) {
        refreshPending.value = false
        void operate('refresh')
      }
    }
  }

  return {
    account,
    token,
    status,
    busy: readonly(busy),
    failedAction: readonly(failedAction),
    operationError: readonly(operationError),
    refresh: () => operate('refresh'),
    enable: () => operate('enable'),
    disable: () => operate('disable'),
  }
}

export const useBrowserPushLifecycle = () => {
  const { account, token, refresh } = useBrowserPush()
  const tenant = useTenant()
  let mounted = false

  const onVisibility = () => {
    if (document.visibilityState === 'visible') void refresh()
  }
  const onWorkerMessage = (event: MessageEvent) => {
    if (event.source instanceof ServiceWorker && event.source.scriptURL === new URL(pushWorker, location.origin).href
      && event.data?.type === 'pushsubscriptionchange') void refresh()
  }
  const onStorage = (event: StorageEvent) => {
    if (event.key === enrollmentStorageKey) void refresh()
  }

  watch([account, token, () => tenant.value?.vapid_public_key], () => {
    if (mounted) void refresh()
  })
  onMounted(() => {
    mounted = true
    document.addEventListener('visibilitychange', onVisibility)
    navigator.serviceWorker?.addEventListener('message', onWorkerMessage)
    window.addEventListener('focus', onVisibility)
    window.addEventListener('storage', onStorage)
    void refresh()
  })
  onBeforeUnmount(() => {
    if (!mounted) return
    mounted = false
    document.removeEventListener('visibilitychange', onVisibility)
    navigator.serviceWorker?.removeEventListener('message', onWorkerMessage)
    window.removeEventListener('focus', onVisibility)
    window.removeEventListener('storage', onStorage)
  })
}
