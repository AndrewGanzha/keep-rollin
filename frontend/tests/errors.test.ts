import { describe, expect, it } from 'vitest'
import { ApiError, toApiError } from '../app/shared/api/errors'

describe('ApiError', () => {
  it('maps problem fields', () => {
    const error = toApiError(
      {
        type: 'urn:keeprollin:error:slot_taken',
        title: 'Слот занят',
        status: 409,
        code: 'slot_taken',
        trace_id: 'trace-1',
        fields: { start_time: 'пересекается' },
      },
      new Response(null, { status: 409 }),
    )

    expect(error).toBeInstanceOf(ApiError)
    expect(error.code).toBe('slot_taken')
    expect(error.traceId).toBe('trace-1')
    expect(error.fields.start_time).toBe('пересекается')
  })

  it('falls back for non-problem payloads', () => {
    const error = toApiError(null, new Response(null, { status: 500 }))

    expect(error.code).toBe('unknown_error')
    expect(error.status).toBe(500)
  })
})
