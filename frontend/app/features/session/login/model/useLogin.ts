import { computed, onScopeDispose, ref, shallowRef } from 'vue'
import { confirmMfa, loginRequest, setupMfa, verifyMfa, type LoginResponse, type MfaSetupResponse } from '~/entities/session'
import { ApiError, useApi } from '~/shared/api'
import { safeNext } from '~/shared/lib/safe-next'
import { loginCredentials } from '../../model/credentials'
import { useSession } from '../../model/useSession'

type LoginStep =
  | { kind: 'credentials' }
  | { kind: 'verify'; token: string }
  | { kind: 'setup'; token: string; details?: MfaSetupResponse }
  | { kind: 'recovery'; accessToken: string; codes: string[]; downloaded: boolean }

export const useLogin = () => {
  const api = useApi()
  const { establish, store } = useSession()
  const route = useRoute()
  const step = shallowRef<LoginStep>({ kind: 'credentials' })
  const stage = computed(() => step.value.kind)
  const setup = computed(() => step.value.kind === 'setup' ? step.value.details : undefined)
  const recovery = computed(() => {
    const current = step.value
    return current.kind === 'recovery' ? { codes: current.codes, downloaded: current.downloaded } : undefined
  })
  const pending = ref(false)
  const errorText = ref('')
  const retryAfter = ref(0)
  let retryTimer: ReturnType<typeof setInterval> | undefined
  let disposed = false

  const stopRetryTimer = () => {
    clearInterval(retryTimer)
    retryAfter.value = 0
  }

  const waitBeforeRetry = (seconds: number) => {
    const retryAt = Date.now() + seconds * 1000
    retryAfter.value = Math.ceil(seconds)
    retryTimer = setInterval(() => {
      retryAfter.value = Math.max(0, Math.ceil((retryAt - Date.now()) / 1000))
      if (retryAfter.value === 0) {
        stopRetryTimer()
      }
    }, 1000)
  }

  const backToCredentials = () => {
    if (pending.value) {
      return
    }
    step.value = { kind: 'credentials' }
    errorText.value = ''
    stopRetryTimer()
  }

  onScopeDispose(() => {
    disposed = true
    step.value = { kind: 'credentials' }
    stopRetryTimer()
  })

  const handleError = (caught: unknown) => {
    if (disposed) {
      return
    }
    if (!(caught instanceof ApiError)) {
      errorText.value = 'Не удалось завершить вход. Попробуйте ещё раз.'
      return
    }
    if (caught.status === 429) {
      if (caught.retryAfterSeconds && caught.retryAfterSeconds > 0) {
        waitBeforeRetry(caught.retryAfterSeconds)
      }
      errorText.value = 'Слишком много попыток. Подождите и попробуйте снова.'
      return
    }
    if (stage.value !== 'credentials' && (
      caught.code === 'token_invalid' || caught.code === 'token_expired' || caught.code === 'conflict'
    )) {
      step.value = { kind: 'credentials' }
      errorText.value = 'Подтверждение входа завершилось. Введите email и пароль снова.'
      return
    }
    if (caught.code === 'invalid_credentials') {
      errorText.value = 'Неверный email или пароль.'
    } else if (caught.code === 'invalid_mfa_code') {
      errorText.value = 'Код неверен или уже использован. Введите новый код.'
    } else if (caught.status === 422) {
      errorText.value = stage.value === 'credentials' ? 'Проверьте email и пароль.' : 'Проверьте код подтверждения.'
    } else {
      errorText.value = 'Не удалось завершить вход. Попробуйте ещё раз.'
    }
  }

  const run = async (action: () => Promise<void>) => {
    if (pending.value || retryAfter.value || disposed) {
      return
    }
    pending.value = true
    errorText.value = ''
    try {
      await action()
    } catch (caught) {
      handleError(caught)
    } finally {
      pending.value = false
    }
  }

  const loadSetup = async (token: string) => {
    const details = await setupMfa(api, { mfa_token: token })
    if (!disposed) {
      step.value = { kind: 'setup', token, details }
    }
  }

  const getAccessToken = (response: LoginResponse) => {
    if (!response.access_token || response.mfa_required || response.mfa_setup_required) {
      throw new Error('Missing access token')
    }
    return response.access_token
  }

  const goToDestination = async () => {
    if (!disposed) {
      await navigateTo(safeNext(route.query.next, store.isStaff ? '/admin' : '/account/rentals'))
    }
  }

  const submit = (email: string, password: string) => run(async () => {
    if (stage.value !== 'credentials') {
      return
    }
    const credentials = loginCredentials.safeParse({ email, password })
    if (!credentials.success) {
      errorText.value = credentials.error.issues[0]?.message ?? 'Проверьте email и пароль.'
      return
    }
    const response = await loginRequest(api, credentials.data)
    if (disposed) {
      return
    }
    if (response.mfa_setup_required || response.mfa_required) {
      if (!response.mfa_token) {
        throw new Error('Missing MFA challenge')
      }
      if (response.mfa_setup_required) {
        step.value = { kind: 'setup', token: response.mfa_token }
        await loadSetup(response.mfa_token)
      } else {
        step.value = { kind: 'verify', token: response.mfa_token }
      }
      return
    }
    await establish(getAccessToken(response))
    await goToDestination()
  })

  const requestSetup = () => run(async () => {
    const current = step.value
    if (current.kind === 'setup' && !current.details) {
      await loadSetup(current.token)
    }
  })

  const submitCode = (value: string) => run(async () => {
    const current = step.value
    const code = value.trim()
    if (current.kind === 'setup' && current.details) {
      if (!/^[0-9]{6}$/.test(code)) {
        errorText.value = 'Введите шесть цифр из приложения.'
        return
      }
      const response = await confirmMfa(api, { mfa_token: current.token, code })
      if (!disposed) {
        step.value = {
          kind: 'recovery',
          accessToken: getAccessToken(response),
          codes: response.recovery_codes,
          downloaded: false,
        }
      }
    } else if (current.kind === 'verify') {
      if (code.length < 6 || code.length > 32) {
        errorText.value = 'Введите код из приложения или код восстановления.'
        return
      }
      const response = await verifyMfa(api, { mfa_token: current.token, code })
      if (!disposed) {
        await establish(getAccessToken(response))
        await goToDestination()
      }
    }
  })

  const downloadRecoveryCodes = () => {
    const current = step.value
    if (current.kind !== 'recovery' || current.downloaded || !current.codes.length) {
      return
    }
    const url = URL.createObjectURL(new Blob([current.codes.join('\n') + '\n'], { type: 'text/plain' }))
    try {
      const link = document.createElement('a')
      link.href = url
      link.download = 'keep-rollin-recovery-codes.txt'
      link.click()
      step.value = { ...current, downloaded: true }
    } finally {
      setTimeout(() => URL.revokeObjectURL(url), 0)
    }
  }

  const continueAfterRecovery = () => run(async () => {
    const current = step.value
    if (current.kind !== 'recovery') {
      return
    }
    await establish(current.accessToken)
    step.value = { kind: 'credentials' }
    await goToDestination()
  })

  return {
    stage, setup, recovery, pending, errorText, retryAfter,
    submit, requestSetup, submitCode, backToCredentials, downloadRecoveryCodes, continueAfterRecovery,
  }
}
