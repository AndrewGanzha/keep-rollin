import type { components } from '~/shared/api/schema'

export type Session = components['schemas']['Session']
export type LoginRequest = components['schemas']['LoginRequest']
export type LoginResponse = components['schemas']['LoginResponse']
export type MfaTokenRequest = components['schemas']['MfaTokenRequest']
export type MfaCodeRequest = components['schemas']['MfaCodeRequest']
export type MfaSetupResponse = components['schemas']['MfaSetupResponse']
export type MfaConfirmResponse = components['schemas']['MfaConfirmResponse']
export type PasswordForgotRequest = components['schemas']['PasswordForgotRequest']
export type PasswordResetRequest = components['schemas']['PasswordResetRequest']
export type User = components['schemas']['User']
export type UserRole = User['role']
