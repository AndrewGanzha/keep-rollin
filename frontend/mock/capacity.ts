/**
 * Ёмкость пула АКБ (D-23): аренда с `battery_count = k` занимает `k` штук
 * своего `battery_type` на весь интервал. Меряем не «сколько выдали всего»,
 * а пик одновременной занятости.
 */
export interface BatteryCommit {
  battery_type: string
  count: number
  start_ms: number
  end_ms: number
}

/**
 * Пик занятости типа, включая кандидата `extra` (следующая бронь).
 * Интервал полуоткрытый `[start, end)`, поэтому в один момент освобождение
 * считается раньше захвата: `duration - 1` единиц после освобождения влезают.
 */
export const peakUsage = (
  commits: BatteryCommit[],
  batteryType: string,
  extra?: BatteryCommit,
): number => {
  const events: { at: number; delta: number }[] = []

  for (const commit of commits) {
    if (commit.battery_type !== batteryType || commit.count <= 0) {
      continue
    }

    events.push({ at: commit.start_ms, delta: commit.count })
    events.push({ at: commit.end_ms, delta: -commit.count })
  }

  if (extra && extra.battery_type === batteryType && extra.count > 0) {
    events.push({ at: extra.start_ms, delta: extra.count })
    events.push({ at: extra.end_ms, delta: -extra.count })
  }

  events.sort((left, right) => left.at - right.at || left.delta - right.delta)

  let running = 0
  let peak = 0

  for (const event of events) {
    running += event.delta
    peak = Math.max(peak, running)
  }

  return peak
}
