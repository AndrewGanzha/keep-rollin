import { unwrap, type ApiClient } from '~/shared/api'
import type { LoginRequest, LoginResponse, Session } from '../model/session.types'

export const loginRequest = async (api: ApiClient, payload: LoginRequest): Promise<LoginResponse> =>
  unwrap(await api.POST('/api/v1/auth/login', { body: payload }))

export const fetchSession = async (api: ApiClient): Promise<Session> =>
  unwrap(await api.GET('/api/v1/auth/session'))
