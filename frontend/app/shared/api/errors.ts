import type { components } from './schema'

export type Problem = components['schemas']['Problem']

/**
 * Единая ошибка API. UI никогда не показывает `detail` напрямую:
 * текст берётся по `code`, поля — по `fields`.
 */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly fields: Record<string, string>
  readonly traceId: string | null
  readonly retryAfterSeconds: number | null

  constructor(problem: Partial<Problem>, status: number, retryAfterSeconds: number | null = null) {
    super(problem.title ?? problem.detail ?? `HTTP ${status}`)
    this.name = 'ApiError'
    this.status = status
    this.code = problem.code ?? 'unknown_error'
    this.fields = problem.fields ?? {}
    this.traceId = problem.trace_id ?? null
    this.retryAfterSeconds = retryAfterSeconds
  }
}

const isProblem = (value: unknown): value is Problem =>
  typeof value === 'object' && value !== null && 'code' in value

export const toApiError = (error: unknown, response: Response): ApiError => {
  const retryAfter = response.headers.get('Retry-After')
  const seconds = retryAfter && /^\d+$/.test(retryAfter) ? Number(retryAfter) : null
  return new ApiError(isProblem(error) ? error : {}, response.status,
    Number.isSafeInteger(seconds) ? seconds : null)
}
