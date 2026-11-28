<script setup lang="ts">
import type { AdminRentalStatus } from '~/entities/rental'
import { rentalStatusLabels } from '~/entities/rental'
import type {
  AdminSchedule,
  ScheduleBlockInterval,
  ScheduleInterval,
  ScheduleLot,
  ScheduleRentalInterval,
} from '~/entities/schedule'
import type { BlockRange } from '~/features/admin-schedule'
import { addDays, dayKeyOf, formatDateTime, zonedDayStartIso } from '~/shared/lib'
import { EmptyState } from '~/shared/ui'

const props = withDefaults(
  defineProps<{
    schedule: AdminSchedule | null
    days: string[]
    todayKey: string
    status?: AdminRentalStatus
    timeZone?: string
    loading?: boolean
  }>(),
  { status: undefined, timeZone: undefined, loading: false },
)

const emit = defineEmits<{
  'select-rental': [interval: ScheduleRentalInterval]
  'select-block': [interval: ScheduleBlockInterval]
  'block-range': [range: BlockRange]
}>()

const DAY_WIDTH = 44
const ROW_HEIGHT = 44

const weekdayFormatter = new Intl.DateTimeFormat('ru-RU', {
  weekday: 'short',
  timeZone: 'UTC',
})

const dayStarts = computed(() => {
  const starts = props.days.map(day => Date.parse(zonedDayStartIso(day, props.timeZone)))
  const last = props.days[props.days.length - 1]

  if (last) {
    starts.push(Date.parse(zonedDayStartIso(addDays(last, 1), props.timeZone)))
  }

  return starts
})

const monthStart = computed(() => dayStarts.value[0] ?? 0)
const monthEnd = computed(() => dayStarts.value[dayStarts.value.length - 1] ?? 0)

const isWeekend = (day: string): boolean => {
  const weekday = new Date(`${day}T00:00:00.000Z`).getUTCDay()

  return weekday === 0 || weekday === 6
}

const weekdayLabel = (day: string): string => weekdayFormatter.format(new Date(`${day}T00:00:00.000Z`))

const intervalsByLot = computed(() => {
  const map = new Map<string, ScheduleInterval[]>()

  for (const interval of props.schedule?.intervals ?? []) {
    if (interval.kind === 'rental' && props.status && interval.status !== props.status) {
      continue
    }

    const list = map.get(interval.lot_id) ?? []
    list.push(interval)
    map.set(interval.lot_id, list)
  }

  return map
})

interface Bar {
  interval: ScheduleInterval
  left: number
  width: number
  clippedStart: boolean
  clippedEnd: boolean
}

const dayIndexAt = (timeMs: number): number => {
  const key = dayKeyOf(new Date(timeMs), props.timeZone)

  return props.days.indexOf(key)
}

const clamp01 = (value: number): number => Math.min(1, Math.max(0, value))

const barFor = (interval: ScheduleInterval): Bar | null => {
  if (!props.days.length) {
    return null
  }

  const startMs = Date.parse(interval.start_time)
  const endMs = Date.parse(interval.end_time)
  const start = Math.max(startMs, monthStart.value)
  const end = Math.min(endMs, monthEnd.value)

  if (end <= start) {
    return null
  }

  const firstIndex = Math.min(Math.max(dayIndexAt(start), 0), props.days.length - 1)
  const lastIndex = Math.min(Math.max(dayIndexAt(end - 1), 0), props.days.length - 1)
  const firstStart = dayStarts.value[firstIndex]!
  const firstNext = dayStarts.value[firstIndex + 1]!
  const lastStart = dayStarts.value[lastIndex]!
  const lastNext = dayStarts.value[lastIndex + 1]!
  const startFraction = clamp01((start - firstStart) / (firstNext - firstStart))
  const endFraction = clamp01((end - lastStart) / (lastNext - lastStart))
  const left = (firstIndex + startFraction) * DAY_WIDTH
  const right = (lastIndex + endFraction) * DAY_WIDTH

  return {
    interval,
    left,
    width: Math.max(right - left, 10),
    clippedStart: interval.clipped_start || startMs < monthStart.value,
    clippedEnd: interval.clipped_end || endMs > monthEnd.value,
  }
}

const barsFor = (lotId: string): Bar[] =>
  (intervalsByLot.value.get(lotId) ?? [])
    .map(barFor)
    .filter((bar): bar is Bar => bar !== null)

const barLabel = (bar: Bar): string => bar.interval.kind === 'block'
  ? bar.interval.reason
  : bar.interval.user_name

const barTitle = (bar: Bar): string => {
  const period = `${formatDateTime(bar.interval.start_time, props.timeZone)} — ${formatDateTime(bar.interval.end_time, props.timeZone)}`

  return bar.interval.kind === 'block'
    ? `Блокировка: ${bar.interval.reason} · ${period}`
    : `${bar.interval.user_name} · ${rentalStatusLabels[bar.interval.status]} · ${period} · ${bar.interval.battery_count} АКБ`
}

const barClass = (bar: Bar): string => bar.interval.kind === 'block'
  ? 'gant__bar--block'
  : `gant__bar--${bar.interval.status}`

const openInterval = (interval: ScheduleInterval) => {
  if (interval.kind === 'block') {
    emit('select-block', interval)
  } else {
    emit('select-rental', interval)
  }
}

interface DragState {
  lotId: string
  from: string
  to: string
}

const drag = ref<DragState | null>(null)

const dragRange = computed(() => {
  if (!drag.value) {
    return null
  }

  return drag.value.from <= drag.value.to
    ? { from: drag.value.from, to: drag.value.to }
    : { from: drag.value.to, to: drag.value.from }
})

const isSelected = (lotId: string, day: string): boolean => {
  const range = dragRange.value

  return drag.value?.lotId === lotId
    && range !== null
    && day >= range.from
    && day <= range.to
}

const startDrag = (lot: ScheduleLot, day: string, event: PointerEvent) => {
  if (drag.value || (event.pointerType === 'mouse' && event.button !== 0)) {
    return
  }

  if (event.pointerType === 'mouse') {
    event.preventDefault()
  }

  drag.value = { lotId: lot.id, from: day, to: day }

  const finish = () => {
    window.removeEventListener('pointerup', finish)
    window.removeEventListener('pointercancel', cancel)
    const current = drag.value
    drag.value = null

    if (!current) {
      return
    }

    const fromDay = current.from <= current.to ? current.from : current.to
    const toDay = current.from <= current.to ? current.to : current.from
    emit('block-range', { lotId: lot.id, lotName: lot.name, fromDay, toDay })
  }

  const cancel = () => {
    window.removeEventListener('pointerup', finish)
    window.removeEventListener('pointercancel', cancel)
    drag.value = null
  }

  window.addEventListener('pointerup', finish, { once: true })
  window.addEventListener('pointercancel', cancel, { once: true })
}

const extendDrag = (lotId: string, day: string) => {
  if (drag.value?.lotId === lotId) {
    drag.value = { ...drag.value, to: day }
  }
}
</script>

<template>
  <div
    class="gant"
    :class="{ 'gant--dragging': drag !== null }"
  >
    <EmptyState
      v-if="!loading && (!schedule || schedule.lots.length === 0)"
      title="Лотов нет"
      description="Расписание появится после создания лотов"
    />

    <div
      v-else
      class="gant__scroll"
    >
      <div
        class="gant__inner"
        :style="{ width: `${180 + days.length * DAY_WIDTH}px` }"
      >
        <div class="gant__header">
          <div class="gant__corner">
            Лот
          </div>
          <div class="gant__head-row">
            <div
              v-for="day in days"
              :key="day"
              class="gant__head"
              :class="{
                'gant__head--weekend': isWeekend(day),
                'gant__head--today': day === todayKey,
              }"
            >
              <span class="gant__head-day">{{ Number(day.slice(8)) }}</span>
              <small>{{ weekdayLabel(day) }}</small>
            </div>
          </div>
        </div>

        <div
          v-for="lot in schedule?.lots ?? []"
          :key="lot.id"
          class="gant__row"
        >
          <div class="gant__lot">
            <span class="gant__lot-name">{{ lot.name }}</span>
            <small class="muted">{{ lot.rental_unit === 'hour' ? 'по часам' : 'посуточно' }}</small>
          </div>

          <div
            class="gant__track"
            :style="{ width: `${days.length * DAY_WIDTH}px`, height: `${ROW_HEIGHT}px` }"
          >
            <button
              v-for="day in days"
              :key="day"
              type="button"
              class="gant__cell"
              :class="{
                'gant__cell--weekend': isWeekend(day),
                'gant__cell--today': day === todayKey,
                'gant__cell--selected': isSelected(lot.id, day),
              }"
              :aria-label="`${lot.name}, ${day}`"
              @pointerdown="startDrag(lot, day, $event)"
              @pointerenter="extendDrag(lot.id, day)"
            />

            <button
              v-for="bar in barsFor(lot.id)"
              :key="`${bar.interval.kind}-${bar.interval.id}`"
              type="button"
              class="gant__bar"
              :class="[
                barClass(bar),
                {
                  'gant__bar--clip-start': bar.clippedStart,
                  'gant__bar--clip-end': bar.clippedEnd,
                },
              ]"
              :style="{ left: `${bar.left}px`, width: `${bar.width}px` }"
              :title="barTitle(bar)"
              @pointerdown.stop
              @click.stop="openInterval(bar.interval)"
            >
              <span class="gant__bar-label">{{ barLabel(bar) }}</span>
            </button>
          </div>
        </div>
      </div>
    </div>

    <div
      v-if="loading"
      class="gant__loading"
    >
      <i
        class="pi pi-spin pi-spinner"
        aria-hidden="true"
      />
    </div>
  </div>
</template>

<style scoped>
.gant {
  position: relative;
}

.gant__scroll {
  max-width: 100%;
  overflow: auto;
  border: 1px solid var(--p-content-border-color);
  border-radius: var(--p-content-border-radius);
  overscroll-behavior-x: contain;
}

.gant__inner {
  min-width: max-content;
}

.gant__header,
.gant__row {
  display: flex;
}

.gant__header {
  position: sticky;
  top: 0;
  z-index: 4;
  background: var(--p-content-background);
  border-bottom: 1px solid var(--p-content-border-color);
}

.gant__row {
  border-bottom: 1px solid var(--p-content-border-color);
}

.gant__row:last-child {
  border-bottom: none;
}

.gant__corner,
.gant__lot {
  position: sticky;
  left: 0;
  z-index: 3;
  display: flex;
  width: 180px;
  flex: none;
  flex-direction: column;
  justify-content: center;
  gap: 2px;
  padding: 4px 10px;
  background: var(--p-content-background);
  border-right: 1px solid var(--p-content-border-color);
}

.gant__corner {
  z-index: 5;
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--p-text-muted-color);
}

.gant__lot-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 600;
  font-size: 0.85rem;
}

.gant__head-row {
  display: flex;
}

.gant__head {
  display: flex;
  width: 44px;
  flex: none;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 1px;
  padding: 4px 0;
  border-right: 1px solid var(--p-content-border-color);
  font-size: 0.7rem;
  line-height: 1.1;
}

.gant__head small {
  color: var(--p-text-muted-color);
  font-size: 0.62rem;
  text-transform: lowercase;
}

.gant__head--weekend,
.gant__cell--weekend {
  background: color-mix(in srgb, var(--p-text-muted-color) 7%, var(--p-content-background));
}

.gant__head--today {
  box-shadow: inset 0 2px 0 var(--p-primary-color);
}

.gant__head-day {
  font-weight: 600;
}

.gant__track {
  position: relative;
  display: flex;
  flex: none;
}

.gant__cell {
  width: 44px;
  height: 44px;
  flex: none;
  padding: 0;
  border: none;
  border-right: 1px solid var(--p-content-border-color);
  background: transparent;
  cursor: pointer;
  touch-action: pan-x pan-y;
}

.gant__cell:hover {
  background: color-mix(in srgb, var(--p-primary-color) 8%, transparent);
}

.gant__cell--today {
  box-shadow: inset 0 0 0 2px var(--p-primary-color);
}

.gant__cell--selected {
  background: color-mix(in srgb, var(--p-primary-color) 22%, transparent);
}

.gant--dragging {
  user-select: none;
}

.gant__bar {
  position: absolute;
  top: 4px;
  bottom: 4px;
  z-index: 2;
  display: flex;
  align-items: center;
  padding: 0 6px;
  border: none;
  border-left: 3px solid transparent;
  border-radius: 4px;
  color: inherit;
  font: inherit;
  font-size: 0.68rem;
  text-align: left;
  cursor: pointer;
  overflow: hidden;
}

.gant__bar:hover {
  filter: brightness(0.96);
}

.gant__bar-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.gant__bar--booked {
  border-left-color: var(--p-blue-500);
  background: color-mix(in srgb, var(--p-blue-500) 22%, var(--p-content-background));
}

.gant__bar--active {
  border-left-color: var(--p-green-500);
  background: color-mix(in srgb, var(--p-green-500) 24%, var(--p-content-background));
}

.gant__bar--overdue {
  border-left-color: var(--p-red-500);
  background: color-mix(in srgb, var(--p-red-500) 26%, var(--p-content-background));
}

.gant__bar--completed {
  border-left-color: var(--p-surface-400);
  background: color-mix(in srgb, var(--p-surface-400) 22%, var(--p-content-background));
}

.gant__bar--block {
  border-left-color: var(--p-surface-600);
  background: repeating-linear-gradient(
    135deg,
    color-mix(in srgb, var(--p-surface-500) 30%, var(--p-content-background)) 0 6px,
    color-mix(in srgb, var(--p-surface-500) 12%, var(--p-content-background)) 6px 12px
  );
}

.gant__bar--clip-start::after,
.gant__bar--clip-end::after {
  position: absolute;
  top: 50%;
  font-weight: 700;
  transform: translateY(-50%);
}

.gant__bar--clip-start::after {
  content: '‹';
  left: 0;
  padding-left: 2px;
}

.gant__bar--clip-end::after {
  content: '›';
  right: 2px;
}

.gant__loading {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--p-content-border-radius);
  background: color-mix(in srgb, var(--p-content-background) 70%, transparent);
  color: var(--p-primary-color);
  font-size: 1.4rem;
}

@media (max-width: 640px) {
  .gant__corner,
  .gant__lot {
    width: 140px;
  }

  .gant__lot-name {
    font-size: 0.78rem;
  }
}
</style>
