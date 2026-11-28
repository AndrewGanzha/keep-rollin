<script setup lang="ts">
import type {
  AdminRental,
  AdminRentalStatus,
  CancelAdminRentalRequest,
  CloseRentalRequest,
} from '~/entities/rental'
import type { ScheduleBlockInterval, ScheduleRentalInterval } from '~/entities/schedule'
import { useAdminRentals } from '~/features/admin-rentals'
import { useAdminSchedule, type BlockRange } from '~/features/admin-schedule'
import { ErrorState, PageHeading } from '~/shared/ui'
import { AdminRentalDetails, AdminRentalsCalendar } from '~/widgets/admin-rentals'
import { AdminScheduleGrid, BlockDialog } from '~/widgets/admin-schedule'

definePageMeta({ layout: 'admin', middleware: ['auth', 'role'] })

useHead({ title: 'Аренды — админка' })

type Mode = 'days' | 'hours'

const mode = ref<Mode>('days')
const rentals = useAdminRentals(computed(() => mode.value === 'hours'))
const schedule = await useAdminSchedule()

watch(mode, (view) => {
  if (view === 'days') void schedule.refresh()
})

const selected = ref<AdminRental | null>(null)
const blockOpen = ref(false)
const blockRange = ref<BlockRange | null>(null)
const blockTarget = ref<ScheduleBlockInterval | null>(null)

const modeOptions: { label: string; value: Mode }[] = [
  { label: 'Дни месяца', value: 'days' },
  { label: 'Часы', value: 'hours' },
]

const statusOptions: { label: string; value: AdminRentalStatus }[] = [
  { label: 'Забронировано', value: 'booked' },
  { label: 'Активна', value: 'active' },
  { label: 'Просрочена', value: 'overdue' },
  { label: 'Завершена', value: 'completed' },
  { label: 'Отменена', value: 'cancelled' },
]

const currentError = computed(() => (mode.value === 'days' ? schedule.error.value : rentals.error.value))
const detailsPending = computed(() => (mode.value === 'days' ? schedule.acting.value : rentals.acting.value))
const timeZone = computed(() => (mode.value === 'days' ? schedule.timeZone.value : rentals.timeZone.value))

const blockLotName = computed(() => {
  if (blockTarget.value) {
    return schedule.data.value?.lots.find(lot => lot.id === blockTarget.value?.lot_id)?.name ?? ''
  }

  return blockRange.value?.lotName ?? ''
})

const refresh = () => (mode.value === 'days' ? schedule.refresh() : rentals.refresh())

const openScheduleRental = async (interval: ScheduleRentalInterval) => {
  const rental = await schedule.openRental(interval)

  if (rental) {
    selected.value = rental
  }
}

const openBlockRange = (range: BlockRange) => {
  blockRange.value = range
  blockTarget.value = null
  blockOpen.value = true
}

const openBlock = (block: ScheduleBlockInterval) => {
  blockTarget.value = block
  blockRange.value = null
  blockOpen.value = true
}

const createBlock = async (reason: string) => {
  const range = blockRange.value

  if (!range) {
    return
  }

  if (await schedule.createBlock(range.lotId, range.fromDay, range.toDay, reason)) {
    blockOpen.value = false
  }
}

const removeBlock = async (block: ScheduleBlockInterval) => {
  if (await schedule.removeBlock(block)) {
    blockOpen.value = false
  }
}

const onClose = async (rental: AdminRental, payload: CloseRentalRequest) => {
  const done = mode.value === 'days'
    ? await schedule.close(rental, payload)
    : await rentals.close(rental, payload)

  if (done) {
    selected.value = null
  }
}

const onCancel = async (rental: AdminRental, payload: CancelAdminRentalRequest) => {
  const done = mode.value === 'days'
    ? await schedule.cancel(rental, payload)
    : await rentals.cancel(rental, payload)

  if (done) {
    selected.value = null
  }
}
</script>

<template>
  <div class="stack">
    <PageHeading
      title="Аренды"
      subtitle="Гант «лоты × дни» и часовой таймлайн"
    />

    <div class="row toolbar">
      <SelectButton
        v-model="mode"
        :options="modeOptions"
        option-label="label"
        option-value="value"
        :allow-empty="false"
        aria-label="Вид календаря"
      />

      <Select
        v-model="rentals.status.value"
        :options="statusOptions"
        option-label="label"
        option-value="value"
        placeholder="Все статусы"
        show-clear
      />
    </div>

    <div
      v-if="mode === 'days'"
      class="row period-nav"
    >
      <Button
        icon="pi pi-chevron-left"
        text
        rounded
        aria-label="Предыдущий месяц"
        @click="schedule.shift(-1)"
      />
      <Button
        label="Сегодня"
        size="small"
        outlined
        :disabled="schedule.anchor.value === schedule.todayKey.value"
        @click="schedule.anchor.value = schedule.todayKey.value"
      />
      <Button
        icon="pi pi-chevron-right"
        text
        rounded
        aria-label="Следующий месяц"
        @click="schedule.shift(1)"
      />
      <span class="period-nav__label">{{ schedule.monthLabel.value }}</span>
    </div>

    <ErrorState
      v-if="currentError"
      :error="currentError"
      @retry="refresh"
    />

    <template v-else>
      <AdminScheduleGrid
        v-if="mode === 'days'"
        :schedule="schedule.data.value ?? null"
        :days="schedule.days.value"
        :today-key="schedule.todayKey.value"
        :status="rentals.status.value"
        :time-zone="schedule.timeZone.value"
        :loading="schedule.pending.value"
        @select-rental="openScheduleRental"
        @select-block="openBlock"
        @block-range="openBlockRange"
      />

      <AdminRentalsCalendar
        v-else
        v-model:view="rentals.view.value"
        v-model:anchor="rentals.anchor.value"
        :rentals="rentals.data.value?.items ?? []"
        :today-key="rentals.todayKey.value"
        :loading="rentals.pending.value"
        :time-zone="rentals.timeZone.value"
        @select="selected = $event"
      />

      <BlockDialog
        v-model:visible="blockOpen"
        :block="blockTarget"
        :range="blockRange"
        :lot-name="blockLotName"
        :pending="schedule.saving.value"
        :time-zone="schedule.timeZone.value"
        @create="createBlock"
        @delete="removeBlock"
      />

      <AdminRentalDetails
        v-model:rental="selected"
        :pending="detailsPending"
        :time-zone="timeZone"
        @close="onClose"
        @cancel="onCancel"
      />
    </template>
  </div>
</template>

<style scoped>
.toolbar {
  flex-wrap: wrap;
  justify-content: space-between;
}

.period-nav {
  align-items: center;
}

.period-nav__label {
  font-weight: 700;
  font-size: 1.05rem;
  text-transform: capitalize;
}
</style>
