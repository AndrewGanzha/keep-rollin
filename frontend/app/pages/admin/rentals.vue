<script setup lang="ts">
import type { AdminRentalStatus } from '~/entities/rental'
import { useTenant } from '~/entities/tenant'
import { useAdminRentals } from '~/features/admin-rentals'
import { ErrorState, PageHeading } from '~/shared/ui'
import { AdminRentalsTable } from '~/widgets/admin-rentals'

definePageMeta({ layout: 'admin', middleware: ['auth', 'role'] })

useHead({ title: 'Аренды — админка' })

const { data, pending, error, refresh, status, acting, close, cancel } = await useAdminRentals()
const tenant = useTenant()
const timeZone = computed(() => tenant.value?.timezone)

const statusOptions: { label: string; value: AdminRentalStatus }[] = [
  { label: 'Забронировано', value: 'booked' },
  { label: 'Активна', value: 'active' },
  { label: 'Просрочена', value: 'overdue' },
  { label: 'Завершена', value: 'completed' },
  { label: 'Отменена', value: 'cancelled' },
]
</script>

<template>
  <div class="stack">
    <PageHeading
      title="Аренды"
      subtitle="Все брони и аренды: закрытие, отмена, статус лота"
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
    <AdminRentalsTable
      v-else
      :rentals="data?.items ?? []"
      :loading="pending"
      :pending="acting"
      :time-zone="timeZone"
      @close="close"
      @cancel="cancel"
    />
  </div>
</template>
