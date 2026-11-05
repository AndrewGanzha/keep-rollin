import { defineStore } from 'pinia'
import type { LoginResponse, Session, User } from '../model/session.types'

export interface SessionState {
  user: User | null
  role: User['role'] | null
  permissions: string[]
  offerAccepted: boolean
}

export const useSessionStore = defineStore('session', () => {
  const user = ref<SessionState['user']>(null)
  const role = ref<SessionState['role']>(null)
  const permissions = ref<string[]>([])
  const offerAccepted = ref(false)

  const isAuthenticated = computed(() => user.value !== null)
  const isStaff = computed(() => role.value === 'admin' || role.value === 'owner')
  const can = (permission: string): boolean => permissions.value.includes(permission)

  const setSession = (session: Session | LoginResponse): void => {
    user.value = session.user
    role.value = session.role
    permissions.value = session.permissions
    offerAccepted.value = 'offer_accepted' in session ? session.offer_accepted : false
  }

  const clear = (): void => {
    user.value = null
    role.value = null
    permissions.value = []
    offerAccepted.value = false
  }

  return {
    user,
    role,
    permissions,
    offerAccepted,
    isAuthenticated,
    isStaff,
    can,
    setSession,
    clear,
  }
})
