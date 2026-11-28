import { toApiError, unwrap, type ApiClient } from '~/shared/api'
import type {
  LoginRequest,
  LoginResponse,
  MfaCodeRequest,
  MfaConfirmResponse,
  MfaSetupResponse,
  MfaTokenRequest,
  PasswordForgotRequest,
  PasswordResetRequest,
  RegisterRequest,
  Session,
} from '../model/session.types'

export const loginRequest = async (api: ApiClient, payload: LoginRequest): Promise<LoginResponse> =>
  unwrap(await api.POST('/api/v1/auth/login', { body: payload }))

export const registerRequest = async (api: ApiClient, payload: RegisterRequest): Promise<LoginResponse> =>
  unwrap(await api.POST('/api/v1/auth/register', { body: payload }))

export const setupMfa = async (api: ApiClient, payload: MfaTokenRequest): Promise<MfaSetupResponse> =>
  unwrap(await api.POST('/api/v1/auth/mfa/setup', { body: payload }))

export const confirmMfa = async (api: ApiClient, payload: MfaCodeRequest): Promise<MfaConfirmResponse> =>
  unwrap(await api.POST('/api/v1/auth/mfa/confirm', { body: payload }))

export const verifyMfa = async (api: ApiClient, payload: MfaCodeRequest): Promise<LoginResponse> =>
  unwrap(await api.POST('/api/v1/auth/mfa/verify', { body: payload }))

export const requestPasswordReset = async (api: ApiClient, payload: PasswordForgotRequest): Promise<void> => {
  unwrap(await api.POST('/api/v1/auth/password/forgot', { body: payload }))
}

export const resetPassword = async (api: ApiClient, payload: PasswordResetRequest): Promise<void> => {
  const result = await api.POST('/api/v1/auth/password/reset', { body: payload })
  if (result.response.status !== 204) {
    throw toApiError(result.error, result.response)
  }
}

export const fetchSession = async (api: ApiClient): Promise<Session> =>
  unwrap(await api.GET('/api/v1/auth/session'))
