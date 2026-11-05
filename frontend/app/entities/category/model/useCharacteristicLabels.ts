import { useApi } from '~/shared/api'
import { fetchCategories } from '../api/category.api'
import type { Category, Characteristic } from './category.types'

export type CharacteristicLabels = Record<string, Characteristic>

/** Справочник характеристик по `code` — для подписей в карточках лотов. */
export const useCharacteristicLabels = () => {
  const api = useApi()

  const { data: categories } = useAsyncData('categories', () => fetchCategories(api))

  const labels = computed<CharacteristicLabels>(() =>
    Object.fromEntries(
      (categories.value ?? []).flatMap((category: Category) =>
        category.characteristics.map(characteristic => [characteristic.code, characteristic] as const),
      ),
    ),
  )

  return { categories, labels }
}
