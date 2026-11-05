import { unwrap, type ApiClient } from '~/shared/api'
import type { Category } from '../model/category.types'

export const fetchCategories = async (api: ApiClient): Promise<Category[]> =>
  unwrap(await api.GET('/api/v1/public/categories'))
