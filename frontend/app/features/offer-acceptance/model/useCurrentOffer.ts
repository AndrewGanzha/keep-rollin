import { fetchCurrentOffer, type PublicOffer } from '~/entities/offer'
import { ApiError, useApi } from '~/shared/api'

export const useCurrentOffer = (key: string) => {
  const api = useApi()
  return useAsyncData(key, async (): Promise<{ offer: PublicOffer | null }> => {
    try {
      return { offer: await fetchCurrentOffer(api) }
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) return { offer: null }
      throw error
    }
  })
}
