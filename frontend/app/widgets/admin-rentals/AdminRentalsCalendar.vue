<script setup lang="ts">
import type { AdminRental } from '~/entities/rental'
import {
  addDays,
  dayKeyToDate,
  daysForView,
  formatTime,
  shiftMonth,
  zonedDayStartIso,
  type CalendarView,
} from '~/shared/lib'

const props = withDefaults(
  defineProps<{
    rentals: AdminRental[]
    view: CalendarView
    anchor: string
    todayKey: string
    loading?: boolean
    timeZone?: string
  }>(),
  { loading: false, timeZone: undefined },
)

const emit = defineEmits<{
  'update:view': [view: CalendarView]
  'update:anchor': [anchor: string]
  select: [rental: AdminRental]
}>()

const HOURS = Array.from({ length: 24 }, (_, index) => index)
const MONTH_ITEMS = 3

const viewOptions: { label: string; value: CalendarView }[] = [
  { label: 'День', value: 'day' },
  { label: 'Неделя', value: 'week' },
  { label: 'Месяц', value: 'month' },
]

const dayFormatter = new Intl.DateTimeFormat('ru-RU', {
  day: 'numeric',
  month: 'long',
  year: 'numeric',
  timeZone: 'UTC',
})
const shortFormatter = new Intl.DateTimeFormat('ru-RU', {
  day: 'numeric',
  month: 'short',
  timeZone: 'UTC',
})
const monthFormatter = new Intl.DateTimeFormat('ru-RU', {
  month: 'long',
  year: 'numeric',
  timeZone: 'UTC',
})
const shortYearFormatter = new Intl.DateTimeFormat('ru-RU', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  timeZone: 'UTC',
})
const weekdayFormatter = new Intl.DateTimeFormat('ru-RU', {
  weekday: 'short',
  timeZone: 'UTC',
})

const days = computed(() => daysForView(props.view, props.anchor))
const monthPrefix = computed(() => props.anchor.slice(0, 7))

const label = computed(() => {
  if (props.view === 'day') {
    return dayFormatter.format(dayKeyToDate(props.anchor))
  }

  if (props.view === 'month') {
    return monthFormatter.format(dayKeyToDate(props.anchor))
  }

  const week = days.value
  return `${shortFormatter.format(dayKeyToDate(week[0]!))} — ${shortYearFormatter.format(dayKeyToDate(week[6]!))}`
})

interface TimedRental {
  rental: AdminRental
  start: number
  end: number
}

interface DaySegment extends TimedRental {
  left: number
  width: number
  lane: number
  lanes: number
}

const dayBounds = (day: string): { start: number; end: number } => ({
  start: Date.parse(zonedDayStartIso(day, props.timeZone)),
  end: Date.parse(zonedDayStartIso(addDays(day, 1), props.timeZone)),
})

const rentalsByDay = computed(() => {
  const map = new Map<string, AdminRental[]>()

  for (const day of days.value) {
    const { start, end } = dayBounds(day)
    map.set(
      day,
      props.rentals
        .filter(rental => Date.parse(rental.start_time) < end && Date.parse(rental.end_time) > start)
        .sort((left, right) => left.start_time.localeCompare(right.start_time)),
    )
  }

  return map
})

const segmentsForDay = (day: string): DaySegment[] => {
  const { start: dayStart, end: dayEnd } = dayBounds(day)
  const items: TimedRental[] = props.rentals
    .map(rental => ({
      rental,
      start: Math.max(Date.parse(rental.start_time), dayStart),
      end: Math.min(Date.parse(rental.end_time), dayEnd),
    }))
    .filter(item => item.start < item.end)
    .sort((left, right) => left.start - right.start)

  const segments: DaySegment[] = []
  let cluster: TimedRental[] = []
  let clusterEnd = 0

  const flush = () => {
    const lanesEnd: number[] = []

    const laidOut = cluster.map((item) => {
      let lane = lanesEnd.findIndex(end => end <= item.start)

      if (lane === -1) {
        lane = lanesEnd.length
        lanesEnd.push(item.end)
      } else {
        lanesEnd[lane] = item.end
      }

      return { ...item, lane }
    })

    const dayMs = dayEnd - dayStart

    for (const item of laidOut) {
      segments.push({
        ...item,
        left: ((item.start - dayStart) / dayMs) * 100,
        width: Math.max(((item.end - item.start) / dayMs) * 100, 0.6),
        lanes: lanesEnd.length,
      })
    }

    cluster = []
    clusterEnd = 0
  }

  for (const item of items) {
    if (cluster.length > 0 && item.start >= clusterEnd) {
      flush()
    }

    clusterEnd = Math.max(clusterEnd, item.end)
    cluster.push(item)
  }

  if (cluster.length > 0) {
    flush()
  }

  return segments
}

const segmentsByDay = computed(() => {
  const map = new Map<string, DaySegment[]>()

  for (const day of days.value) {
    map.set(day, segmentsForDay(day))
  }

  return map
})

const blockStyle = (segment: DaySegment): Record<string, string> => {
  const laneHeight = 100 / segment.lanes

  return {
    left: `${segment.left}%`,
    width: `calc(${segment.width}% - 4px)`,
    top: `calc(${laneHeight * segment.lane}% + 2px)`,
    height: `calc(${laneHeight}% - 4px)`,
  }
}

const rowHeight = (day: string): number => {
  const lanes = Math.max(1, ...(segmentsByDay.value.get(day) ?? []).map(segment => segment.lanes))
  const base = props.view === 'day' ? 64 : 52

  return Math.max(base, lanes * 30)
}

const tickLabel = (hour: number): string => (hour % 3 === 0 ? `${String(hour).padStart(2, '0')}:00` : '')

const segmentTime = (segment: DaySegment): string =>
  `${formatTime(new Date(segment.start).toISOString(), props.timeZone)}–${formatTime(new Date(segment.end).toISOString(), props.timeZone)}`

const blockTitle = (segment: DaySegment): string =>
  `${segment.rental.lot.name} · ${segment.rental.user.name} · ${segmentTime(segment)}`

const shift = (direction: number) => {
  const next = props.view === 'day'
    ? addDays(props.anchor, direction)
    : props.view === 'week'
      ? addDays(props.anchor, 7 * direction)
      : shiftMonth(props.anchor, direction)

  emit('update:anchor', next)
}

const scrollRef = ref<HTMLElement | null>(null)

const scrollToContent = async () => {
  await nextTick()

  const element = scrollRef.value

  if (!element) {
    return
  }

  const segments = [...segmentsByDay.value.values()].flat()
  const earliest = segments.length > 0
    ? Math.min(...segments.map(segment => segment.left))
    : (8 / 24) * 100
  const hourWidth = (element.scrollWidth - 78) / 24

  element.scrollLeft = Math.max((earliest / 100) * 24 * hourWidth - hourWidth, 0)
}

watch(
  [() => props.view, () => props.anchor, () => props.rentals.length],
  scrollToContent,
  { flush: 'post' },
)

onMounted(scrollToContent)

const openDay = (day: string) => {
  emit('update:anchor', day)
  emit('update:view', 'day')
}

const onView = (value: CalendarView) => emit('update:view', value)
</script>

<template>
  <div class="calendar stack">
    <div class="calendar__toolbar">
      <div class="row">
        <Button
          icon="pi pi-chevron-left"
          text
          rounded
          aria-label="Предыдущий период"
          @click="shift(-1)"
        />
        <Button
          label="Сегодня"
          size="small"
          outlined
          :disabled="anchor === todayKey"
          @click="emit('update:anchor', todayKey)"
        />
        <Button
          icon="pi pi-chevron-right"
          text
          rounded
          aria-label="Следующий период"
          @click="shift(1)"
        />
      </div>

      <span class="calendar__label">{{ label }}</span>

      <SelectButton
        :model-value="view"
        :options="viewOptions"
        option-label="label"
        option-value="value"
        :allow-empty="false"
        aria-label="Масштаб календаря"
        @update:model-value="onView"
      />
    </div>

    <Skeleton
      v-if="loading"
      height="420px"
      border-radius="16px"
    />

    <div
      v-if="view === 'month'"
      class="month"
    >
      <div
        v-for="day in days.slice(0, 7)"
        :key="`weekday-${day}`"
        class="month__weekday"
      >
        {{ weekdayFormatter.format(dayKeyToDate(day)) }}
      </div>

      <div
        v-for="day in days"
        :key="day"
        class="month__cell"
        :class="{
          'month__cell--muted': !day.startsWith(monthPrefix),
          'month__cell--today': day === todayKey,
        }"
      >
        <button
          class="month__date"
          type="button"
          @click="openDay(day)"
        >
          {{ Number(day.slice(8)) }}
        </button>

        <div class="month__items">
          <button
            v-for="rental in (rentalsByDay.get(day) ?? []).slice(0, MONTH_ITEMS)"
            :key="rental.id"
            type="button"
            class="month__item"
            :class="`month__item--${rental.status}`"
            :title="`${rental.lot.name} · ${rental.user.name}`"
            @click="emit('select', rental)"
          >
            <span class="dot" />
            <span class="month__time">{{ formatTime(rental.start_time, timeZone) }}</span>
            <span class="month__name">{{ rental.lot.name }}</span>
          </button>

          <button
            v-if="(rentalsByDay.get(day)?.length ?? 0) > MONTH_ITEMS"
            type="button"
            class="month__more"
            @click="openDay(day)"
          >
            +{{ (rentalsByDay.get(day)?.length ?? 0) - MONTH_ITEMS }} ещё
          </button>
        </div>
      </div>
    </div>

    <div
      v-else
      ref="scrollRef"
      class="timeline"
    >
      <div class="timeline__inner">
        <div class="timeline__header">
          <div class="timeline__gutter" />
          <div class="timeline__axis">
            <div
              v-for="hour in HOURS"
              :key="hour"
              class="timeline__tick"
            >
              {{ tickLabel(hour) }}
            </div>
          </div>
        </div>

        <div
          v-for="day in days"
          :key="day"
          class="timeline__row"
          :class="{ 'timeline__row--today': day === todayKey }"
        >
          <div class="timeline__day-label">
            <span class="muted">{{ weekdayFormatter.format(dayKeyToDate(day)) }}</span>
            <span class="timeline__date">{{ Number(day.slice(8)) }}</span>
          </div>

          <div
            class="timeline__track"
            :style="{ height: `${rowHeight(day)}px` }"
          >
            <div
              class="timeline__grid"
              aria-hidden="true"
            >
              <div
                v-for="hour in HOURS"
                :key="hour"
                class="timeline__grid-cell"
              />
            </div>

            <button
              v-for="segment in (segmentsByDay.get(day) ?? [])"
              :key="segment.rental.id"
              type="button"
              class="timeline__block"
              :class="`timeline__block--${segment.rental.status}`"
              :style="blockStyle(segment)"
              :title="blockTitle(segment)"
              @click="emit('select', segment.rental)"
            >
              <span class="timeline__block-time">{{ segmentTime(segment) }}</span>
              <span class="timeline__block-name">{{ segment.rental.lot.name }}</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.calendar__toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.calendar__label {
  font-weight: 700;
  font-size: 1.05rem;
}

.month {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  border: 1px solid var(--p-content-border-color);
  border-radius: var(--p-content-border-radius);
  overflow: hidden;
}

.month__weekday {
  padding: 8px;
  font-size: 0.8rem;
  font-weight: 600;
  text-transform: capitalize;
  color: var(--p-text-muted-color);
  background: var(--p-content-background);
  border-bottom: 1px solid var(--p-content-border-color);
}

.month__cell {
  min-height: 108px;
  padding: 4px;
  border-bottom: 1px solid var(--p-content-border-color);
  border-right: 1px solid var(--p-content-border-color);
  background: var(--p-content-background);
  overflow: hidden;
}

.month__cell:nth-child(7n + 7) {
  border-right: none;
}

.month__cell--muted {
  background: color-mix(in srgb, var(--p-text-muted-color) 6%, var(--p-content-background));
}

.month__cell--today {
  box-shadow: inset 0 0 0 2px var(--p-primary-color);
}

.month__date {
  width: 26px;
  height: 26px;
  margin-bottom: 2px;
  border: none;
  border-radius: 50%;
  background: transparent;
  color: inherit;
  font: inherit;
  font-size: 0.85rem;
  cursor: pointer;
}

.month__date:hover {
  background: var(--p-highlight-background);
}

.month__items {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.month__item,
.month__more {
  display: flex;
  align-items: center;
  gap: 4px;
  width: 100%;
  padding: 2px 4px;
  border: none;
  border-left: 3px solid transparent;
  border-radius: 4px;
  background: transparent;
  color: inherit;
  font: inherit;
  font-size: 0.75rem;
  text-align: left;
  cursor: pointer;
  overflow: hidden;
}

.month__item:hover,
.month__more:hover {
  background: var(--p-highlight-background);
}

.month__time {
  color: var(--p-text-muted-color);
  white-space: nowrap;
}

.month__name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.month__more {
  color: var(--p-text-muted-color);
}

.month__item--booked {
  border-left-color: var(--p-blue-500);
}

.month__item--active {
  border-left-color: var(--p-green-500);
}

.month__item--overdue {
  border-left-color: var(--p-red-500);
}

.month__item--completed,
.month__item--cancelled {
  border-left-color: var(--p-surface-400);
}

.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  flex: none;
}

.timeline {
  overflow-x: auto;
  border: 1px solid var(--p-content-border-color);
  border-radius: var(--p-content-border-radius);
}

.timeline__inner {
  min-width: 820px;
}

.timeline__header,
.timeline__row {
  display: grid;
  grid-template-columns: 78px 1fr;
}

.timeline__header {
  border-bottom: 1px solid var(--p-content-border-color);
}

.timeline__row {
  border-bottom: 1px solid var(--p-content-border-color);
}

.timeline__row:last-child {
  border-bottom: none;
}

.timeline__row--today {
  background: color-mix(in srgb, var(--p-primary-color) 4%, transparent);
}

.timeline__gutter,
.timeline__day-label {
  border-right: 1px solid var(--p-content-border-color);
}

.timeline__axis {
  display: grid;
  grid-template-columns: repeat(24, 1fr);
}

.timeline__tick {
  padding: 4px;
  border-right: 1px solid var(--p-content-border-color);
  color: var(--p-text-muted-color);
  font-size: 0.7rem;
  white-space: nowrap;
}

.timeline__tick:last-child {
  border-right: none;
}

.timeline__day-label {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  padding: 4px;
  font-size: 0.75rem;
}

.timeline__date {
  font-weight: 700;
  font-size: 1rem;
}

.timeline__track {
  position: relative;
}

.timeline__grid {
  position: absolute;
  inset: 0;
  display: grid;
  grid-template-columns: repeat(24, 1fr);
}

.timeline__grid-cell {
  border-right: 1px solid var(--p-content-border-color);
}

.timeline__grid-cell:last-child {
  border-right: none;
}

.timeline__block {
  position: absolute;
  z-index: 1;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 2px 6px;
  border: none;
  border-left: 3px solid transparent;
  border-radius: 4px;
  color: inherit;
  font: inherit;
  font-size: 0.7rem;
  text-align: left;
  overflow: hidden;
  white-space: nowrap;
  cursor: pointer;
}

.timeline__block:hover {
  filter: brightness(0.97);
}

.timeline__block-time {
  color: var(--p-text-muted-color);
}

.timeline__block-name {
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
}

.timeline__block--booked {
  border-left-color: var(--p-blue-500);
  background: color-mix(in srgb, var(--p-blue-500) 12%, transparent);
}

.timeline__block--active {
  border-left-color: var(--p-green-500);
  background: color-mix(in srgb, var(--p-green-500) 14%, transparent);
}

.timeline__block--overdue {
  border-left-color: var(--p-red-500);
  background: color-mix(in srgb, var(--p-red-500) 16%, transparent);
}

.timeline__block--completed,
.timeline__block--cancelled {
  border-left-color: var(--p-surface-400);
  background: color-mix(in srgb, var(--p-surface-400) 16%, transparent);
}

@media (max-width: 640px) {
  .calendar__toolbar {
    align-items: stretch;
  }

  .calendar__label {
    order: -1;
    width: 100%;
  }

  .month__cell {
    min-height: 84px;
  }

  .month__time {
    display: none;
  }

  .month__item {
    font-size: 0.7rem;
  }
}
</style>
