import { safeNext } from '~/shared/lib/safe-next'

export const offerReturn = (next: unknown) => {
  const fallback = '/account/verification'
  const target = safeNext(next, fallback)
  const pathname = new URL(target, 'https://keep-rollin.invalid').pathname.replace(/\/+$/, '')
  return pathname === '/account/offer' ? fallback : target
}

export const offerGateLocation = (next: string) => ({
  path: '/account/offer',
  query: { next: offerReturn(next) },
})
