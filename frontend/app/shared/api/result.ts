import { toApiError } from './errors'

type ApiResult<T> = {
  data?: T
  error?: unknown
  response: Response
}

/** Разворачивает ответ openapi-fetch: данные или типизированная ошибка. */
export const unwrap = <T>(result: ApiResult<T>): T => {
  if (result.data === undefined) {
    throw toApiError(result.error, result.response)
  }

  return result.data
}
