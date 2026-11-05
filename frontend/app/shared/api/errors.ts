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

  constructor(problem: Partial<Problem>, status: number) {
    super(problem.title ?? problem.detail ?? `HTTP ${status}`)
    this.name = 'ApiError'
    this.status = status
    this.code = problem.code ?? 'unknown_error'
    this.fields = problem.fields ?? {}
    this.traceId = problem.trace_id ?? null
  }
}

const isProblem = (value: unknown): value is Problem =>
  typeof value === 'object' && value !== null && 'code' in value

export const toApiError = (error: unknown, response: Response): ApiError =>
  new ApiError(isProblem(error) ? error : {}, response.status)
