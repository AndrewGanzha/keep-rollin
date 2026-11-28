import { defineStore } from 'pinia'
import type { Session, User } from '../model/session.types'

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

  const setSession = (session: Session): void => {
    user.value = session.user
    role.value = session.role
    permissions.value = session.permissions
    offerAccepted.value = session.offer_accepted
  }

  const markOfferAccepted = (userId: string): void => {
    if (user.value?.id === userId) offerAccepted.value = true
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
    markOfferAccepted,
    clear,
  }
})
