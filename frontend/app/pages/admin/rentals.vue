<script setup lang="ts">
import type {
  AdminRental,
  AdminRentalStatus,
  CancelAdminRentalRequest,
  CloseRentalRequest,
} from '~/entities/rental'
import { useAdminRentals } from '~/features/admin-rentals'
import { ErrorState, PageHeading } from '~/shared/ui'
import { AdminRentalDetails, AdminRentalsCalendar } from '~/widgets/admin-rentals'

definePageMeta({ layout: 'admin', middleware: ['auth', 'role'] })

useHead({ title: 'Аренды — админка' })

const {
  data,
  pending,
  error,
  refresh,
  timeZone,
  todayKey,
  view,
  anchor,
  status,
  selected,
  acting,
  close,
  cancel,
} = await useAdminRentals()

const statusOptions: { label: string; value: AdminRentalStatus }[] = [
  { label: 'Забронировано', value: 'booked' },
  { label: 'Активна', value: 'active' },
  { label: 'Просрочена', value: 'overdue' },
  { label: 'Завершена', value: 'completed' },
  { label: 'Отменена', value: 'cancelled' },
]

const onClose = async (rental: AdminRental, payload: CloseRentalRequest) => {
  if (await close(rental, payload)) {
    selected.value = null
  }
}

const onCancel = async (rental: AdminRental, payload: CancelAdminRentalRequest) => {
  if (await cancel(rental, payload)) {
    selected.value = null
  }
}
</script>

<template>
  <div class="stack">
    <PageHeading
      title="Аренды"
      subtitle="Календарь аренд: день, неделя, месяц"
    />

    <div class="row">
      <Select
        v-model="status"
        :options="statusOptions"
        option-label="label"
        option-value="value"
        placeholder="Все статусы"
        show-clear
      />
    </div>

    <ErrorState
      v-if="error"
      :error="error"
      @retry="refresh"
    />

    <template v-else>
      <AdminRentalsCalendar
        v-model:view="view"
        v-model:anchor="anchor"
        :rentals="data?.items ?? []"
        :today-key="todayKey"
        :loading="pending"
        :time-zone="timeZone"
        @select="selected = $event"
      />

      <AdminRentalDetails
        v-model:rental="selected"
        :pending="acting"
        :time-zone="timeZone"
        @close="onClose"
        @cancel="onCancel"
      />
    </template>
  </div>
</template>
