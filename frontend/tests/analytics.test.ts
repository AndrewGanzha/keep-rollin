import { describe, expect, it, vi } from 'vitest'
import { fetchAnalyticsComparison, fetchAnalyticsCsv, fetchAnalyticsLot } from '~/entities/analytics/api/analytics.api'
import { formatRelativeChange } from '~/entities/analytics/model/comparison'
import { parseAnalyticsDays, pickerDates, presetDays, selectedDays, toAnalyticsRange } from '~/features/admin-analytics/model/analytics-period'
import { createApiClient } from '~/shared/api/client'

describe('analytics reporting periods', () => {
  it('uses browser-local picker dates then sends tenant-local day bounds across DST', () => {
    const dates = { first: '2026-03-07', last: '2026-03-09' }
    expect(selectedDays(pickerDates(dates))).toEqual(dates)
    expect(selectedDays([new Date(2026, 2, 7), null])).toBeNull()
    expect(toAnalyticsRange(dates, 'America/Los_Angeles')).toEqual({
      from: '2026-03-07T08:00:00.000Z',
      to: '2026-03-10T07:00:00.000Z',
    })
  })

  it('uses the first local instant on both a skipped and a repeated midnight', () => {
    expect(toAnalyticsRange({ first: '2026-03-08', last: '2026-03-08' }, 'America/Havana')).toEqual({
      from: '2026-03-08T05:00:00.000Z',
      to: '2026-03-09T04:00:00.000Z',
    })
    expect(toAnalyticsRange({ first: '2026-11-01', last: '2026-11-01' }, 'America/Havana')).toEqual({
      from: '2026-11-01T04:00:00.000Z',
      to: '2026-11-02T05:00:00.000Z',
    })
  })

  it('validates saved dates and enforces 366 elapsed days', () => {
    expect(presetDays('month', '2026-11-28')).toEqual({ first: '2026-11-01', last: '2026-11-28' })
    expect(parseAnalyticsDays('2024-01-01', '2024-12-31', 'UTC')).not.toBeNull()
    expect(parseAnalyticsDays('2024-01-01', '2025-01-01', 'UTC')).toBeNull()
    expect(parseAnalyticsDays('2026-02-30', '2026-03-01', 'UTC')).toBeNull()
    expect(parseAnalyticsDays('2026-11-28', '2026-11-01', 'UTC')).toBeNull()
    expect(parseAnalyticsDays('9999-12-31', '9999-12-31', 'UTC')).toBeNull()
  })
})

describe('analytics comparison', () => {
  it('displays signed percentage changes relative to the earlier period', () => {
    expect(formatRelativeChange(1, 6)).toMatch(/^\+16,7\s%$/)
    expect(formatRelativeChange(-1, 8)).toMatch(/^-12,5\s%$/)
    expect(formatRelativeChange(0, 8)).toMatch(/^0\s%$/)
  })

  it('keeps a zero baseline finite', () => {
    expect(formatRelativeChange(0, 0)).toMatch(/^0\s%$/)
    expect(formatRelativeChange(8, 0)).toBe('—')
  })
})

describe('analytics requests', () => {
  const current = { from: '2026-11-01T00:00:00Z', to: '2026-11-02T00:00:00Z' }
  const baseline = { from: '2026-10-01T00:00:00Z', to: '2026-10-02T00:00:00Z' }
  const apiFor = (response: Response) => {
    const fetch = vi.fn<typeof globalThis.fetch>().mockResolvedValue(response)
    return { api: createApiClient('http://localhost', () => 'test-token', undefined, fetch), fetch }
  }

  it('keeps export bytes and the attachment filename on an authenticated request', async () => {
    const csv = '\ufeffЛот;Статус\r\nЛот 1;active\r\n'
    const { api, fetch } = apiFor(new Response(csv, {
      headers: {
        'Content-Type': 'text/csv; charset=utf-8',
        'Content-Disposition': 'attachment; filename="rental.csv"; filename*=UTF-8\'\'%D0%90%D1%80%D0%B5%D0%BD%D0%B4%D1%8B.csv',
      },
    }))

    const { blob, filename } = await fetchAnalyticsCsv(api, current, 'fallback.csv')
    expect(filename).toBe('Аренды.csv')
    expect(new Uint8Array(await blob.arrayBuffer())).toEqual(new TextEncoder().encode(csv))
    const [url, options] = fetch.mock.calls[0]!
    const request = new URL(String(url))
    expect(request.pathname).toBe('/api/v1/admin/analytics/export')
    expect(Object.fromEntries(request.searchParams)).toEqual({ ...current, report: 'rentals', format: 'csv' })
    expect(options?.headers).toMatchObject({ authorization: 'Bearer test-token' })
  })

  it('returns JSON problem errors from an unsuccessful CSV response', async () => {
    const { api } = apiFor(new Response(JSON.stringify({ code: 'forbidden_role', title: 'Недостаточно прав' }), {
      status: 403,
      headers: { 'Content-Type': 'application/problem+json' },
    }))

    await expect(fetchAnalyticsCsv(api, current, 'fallback.csv')).rejects.toMatchObject({
      code: 'forbidden_role',
      status: 403,
    })
  })

  it('sends the same reporting period for comparison and lot detail pages', async () => {
    const fetch = vi.fn<typeof globalThis.fetch>().mockImplementation(async () => Response.json({}))
    const api = createApiClient('http://localhost', () => 'test-token', undefined, fetch)
    await fetchAnalyticsComparison(api, current, baseline)
    await fetchAnalyticsLot(api, 'lot-1', current, { offset: 100, limit: 100 })

    const [comparisonUrl, detailUrl] = fetch.mock.calls.map(([url]) => new URL(String(url)))
    expect(Object.fromEntries(comparisonUrl!.searchParams))
      .toEqual({ ...current, compare_from: baseline.from, compare_to: baseline.to })
    expect(detailUrl!.pathname).toBe('/api/v1/admin/analytics/lots/lot-1')
    expect(Object.fromEntries(detailUrl!.searchParams)).toEqual({ ...current, offset: '100', limit: '100' })
  })
})
