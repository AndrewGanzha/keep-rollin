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
  top: number
  height: number
  column: number
  columns: number
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
    const columnsEnd: number[] = []

    const laidOut = cluster.map((item) => {
      let column = columnsEnd.findIndex(end => end <= item.start)

      if (column === -1) {
        column = columnsEnd.length
        columnsEnd.push(item.end)
      } else {
        columnsEnd[column] = item.end
      }

      return { ...item, column }
    })

    for (const item of laidOut) {
      segments.push({
        ...item,
        top: (item.start - dayStart) / 60000,
        height: Math.max((item.end - item.start) / 60000, 24),
        columns: columnsEnd.length,
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

const blockStyle = (segment: DaySegment): Record<string, string> => ({
  top: `${segment.top}px`,
  height: `${segment.height}px`,
  left: `calc(${(100 / segment.columns) * segment.column}% + 2px)`,
  width: `calc(${100 / segment.columns}% - 4px)`,
})

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

  const segments = props.view === 'month'
    ? []
    : days.value.flatMap(day => segmentsForDay(day))

  const top = segments.length > 0
    ? Math.min(...segments.map(segment => segment.top))
    : 8 * 60

  element.scrollTop = Math.max(Math.min(top - 60, 1200), 0)
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
      class="timeline"
      :style="{ '--days': days.length }"
    >
      <div class="timeline__inner">
        <div
          v-if="view === 'week'"
          class="timeline__header"
        >
          <div class="timeline__gutter" />
          <div
            v-for="day in days"
            :key="`head-${day}`"
            class="timeline__day-head"
            :class="{ 'timeline__day-head--today': day === todayKey }"
          >
            <span class="muted">{{ weekdayFormatter.format(dayKeyToDate(day)) }}</span>
            <span class="timeline__date">{{ Number(day.slice(8)) }}</span>
          </div>
        </div>

        <div
          ref="scrollRef"
          class="timeline__scroll"
        >
          <div class="timeline__hours">
            <div
              v-for="hour in HOURS"
              :key="hour"
              class="timeline__hour"
            >
              {{ String(hour).padStart(2, '0') }}:00
            </div>
          </div>

          <div
            v-for="day in days"
            :key="day"
            class="timeline__column"
            :class="{ 'timeline__column--today': day === todayKey }"
          >
            <div
              class="timeline__lines"
              aria-hidden="true"
            >
              <div
                v-for="hour in HOURS"
                :key="hour"
                class="timeline__line"
              />
            </div>

            <button
              v-for="segment in segmentsForDay(day)"
              :key="segment.rental.id"
              type="button"
              class="timeline__block"
              :class="`timeline__block--${segment.rental.status}`"
              :style="blockStyle(segment)"
              :title="blockTitle(segment)"
              @click="emit('select', segment.rental)"
            >
              <span class="timeline__block-time">
                {{ segmentTime(segment) }}
              </span>
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
  background: var(--p-surface-50);
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
  min-width: 100%;
}

.timeline__header {
  display: grid;
  grid-template-columns: 52px repeat(var(--days, 7), minmax(110px, 1fr));
  border-bottom: 1px solid var(--p-content-border-color);
}

.timeline__gutter {
  background: var(--p-content-background);
  border-right: 1px solid var(--p-content-border-color);
}

.timeline__day-head {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: 6px 4px;
  background: var(--p-content-background);
  border-right: 1px solid var(--p-content-border-color);
  font-size: 0.8rem;
}

.timeline__day-head:last-child {
  border-right: none;
}

.timeline__day-head--today {
  background: var(--p-highlight-background);
}

.timeline__date {
  font-weight: 700;
  font-size: 1rem;
}

.timeline__scroll {
  display: grid;
  grid-template-columns: 52px repeat(var(--days, 7), minmax(110px, 1fr));
  max-height: 70vh;
  overflow-y: auto;
}

.timeline__hours {
  background: var(--p-content-background);
  border-right: 1px solid var(--p-content-border-color);
}

.timeline__hour {
  height: 60px;
  padding: 2px 4px;
  font-size: 0.7rem;
  color: var(--p-text-muted-color);
  text-align: right;
}

.timeline__column {
  position: relative;
  height: 1440px;
  border-right: 1px solid var(--p-content-border-color);
}

.timeline__column:last-child {
  border-right: none;
}

.timeline__column--today {
  background: color-mix(in srgb, var(--p-primary-color) 4%, transparent);
}

.timeline__lines {
  position: absolute;
  inset: 0;
}

.timeline__line {
  height: 60px;
  border-bottom: 1px solid var(--p-content-border-color);
}

.timeline__block {
  position: absolute;
  z-index: 1;
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: 3px 5px;
  border: none;
  border-left: 3px solid transparent;
  border-radius: 4px;
  color: inherit;
  font: inherit;
  font-size: 0.7rem;
  text-align: left;
  overflow: hidden;
  cursor: pointer;
}

.timeline__block:hover {
  filter: brightness(0.97);
}

.timeline__block-time {
  color: var(--p-text-muted-color);
  white-space: nowrap;
}

.timeline__block-name {
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
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
