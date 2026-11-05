import { useCharacteristicLabels } from '~/entities/category'
import { fetchAvailability, fetchLot } from '~/entities/lot'
import { useApi } from '~/shared/api'

const WINDOW_BEFORE_MS = 60 * 60 * 1000
const WINDOW_AFTER_MS = 14 * 24 * 60 * 60 * 1000

/** Данные страницы лота: карточка + занятость на две недели вперёд. */
export const useLotPage = async (slug: Ref<string>) => {
  const api = useApi()
  const { labels } = useCharacteristicLabels()

  const from = new Date(Date.now() - WINDOW_BEFORE_MS).toISOString()
  const to = new Date(Date.now() + WINDOW_AFTER_MS).toISOString()

  const lot = useAsyncData(
    () => `lot:${slug.value}`,
    () => fetchLot(api, slug.value),
    { watch: [slug] },
  )

  const availability = useAsyncData(
    () => `lot-availability:${slug.value}`,
    () => fetchAvailability(api, slug.value, from, to),
    { watch: [slug] },
  )

  await Promise.all([lot, availability])

  const refresh = async () => {
    await Promise.all([lot.refresh(), availability.refresh()])
  }

  return {
    lot: lot.data,
    availability: availability.data,
    lotError: lot.error,
    labels,
    refresh,
  }
}
