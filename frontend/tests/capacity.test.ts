import { describe, expect, it } from 'vitest'
import { peakUsage, type BatteryCommit } from '../mock/capacity'

const HOUR = 60 * 60 * 1000
const DAY = 24 * HOUR

const commit = (
  count: number,
  startDay: number,
  endDay: number,
  batteryType = '48v',
): BatteryCommit => ({
  battery_type: batteryType,
  count,
  start_ms: startDay * DAY,
  end_ms: endDay * DAY,
})

describe('D-23: пик занятости АКБ', () => {
  it('складывает пересекающиеся аренды и берёт максимум', () => {
    const commits = [
      commit(1, 0, 7),
      commit(2, 2, 4),
      commit(1, 3, 9),
    ]

    expect(peakUsage(commits, '48v')).toBe(4)
  })

  it('не пересекающиеся аренды ёмкость не расходуют', () => {
    const commits = [
      commit(2, 0, 3),
      commit(2, 3, 6),
      commit(2, 10, 12),
    ]

    expect(peakUsage(commits, '48v')).toBe(2)
  })

  it('интервал полуоткрытый: смена в один момент не даёт пик 2', () => {
    expect(peakUsage([commit(1, 0, 3)], '48v', commit(1, 3, 5))).toBe(1)
  })

  it('сценарий заказчика: сток 12, десять по 1 АКБ и одна пара — 12; вторая пара не влезает', () => {
    const commits = [
      ...Array.from({ length: 10 }, () => commit(1, 0, 7)),
      commit(2, 1, 5),
    ]

    expect(peakUsage(commits, '48v')).toBe(12)
    expect(peakUsage(commits, '48v', commit(2, 2, 4))).toBe(14)
    expect(peakUsage(commits, '48v', commit(1, 2, 4))).toBe(13)
  })

  it('после отмены аренды пара снова влезает', () => {
    const busy = [commit(1, 0, 7), commit(2, 1, 5)]
    const limit = 3

    expect(peakUsage(busy, '48v', commit(2, 2, 4))).toBeGreaterThan(limit)
    expect(peakUsage(busy.slice(0, 1), '48v', commit(2, 2, 4))).toBeLessThanOrEqual(limit)
  })

  it('другой тип АКБ и нулевое количество не учитываются', () => {
    const commits = [
      commit(3, 0, 7, '36v'),
      commit(0, 0, 7),
    ]

    expect(peakUsage(commits, '48v')).toBe(0)
    expect(peakUsage(commits, '36v')).toBe(3)
  })

  it('кандидат на другой тип не подмешивается', () => {
    const commits = [commit(1, 0, 5)]

    expect(peakUsage(commits, '48v', commit(5, 0, 5, '36v'))).toBe(1)
  })
})
