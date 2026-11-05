import type { components } from '~/shared/api/schema'

export type Session = components['schemas']['Session']
export type LoginRequest = components['schemas']['LoginRequest']
export type LoginResponse = components['schemas']['LoginResponse']
export type User = components['schemas']['User']
export type UserRole = User['role']
