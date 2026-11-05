import { useCharacteristicLabels } from '~/entities/category'
import { fetchLots, type LotListQuery } from '~/entities/lot'
import { useApi } from '~/shared/api'

/** Загрузка каталога, синхронизированная с query-параметрами маршрута. */
export const useLots = async () => {
  const api = useApi()
  const route = useRoute()

  const { labels } = useCharacteristicLabels()

  const query = computed<LotListQuery>(() => ({
    category_id: typeof route.query.category === 'string' ? route.query.category : undefined,
    q: typeof route.query.q === 'string' ? route.query.q : undefined,
    limit: 24,
    offset: 0,
  }))

  const request = useAsyncData('lots', () => fetchLots(api, query.value), { watch: [query] })
  await request

  return {
    data: request.data,
    pending: request.pending,
    error: request.error,
    refresh: request.refresh,
    labels,
  }
}
