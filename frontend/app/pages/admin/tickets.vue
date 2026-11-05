<script setup lang="ts">
import type { TicketStatus } from '~/entities/ticket'
import { useTenant } from '~/entities/tenant'
import { useTicketQueue } from '~/features/admin-tickets'
import { ErrorState, PageHeading } from '~/shared/ui'
import { TicketQueue } from '~/widgets/admin-tickets'

definePageMeta({ layout: 'admin', middleware: ['auth', 'role'] })

useHead({ title: 'Тикеты — админка' })

const { data, pending, error, refresh, status, updating, update } = await useTicketQueue()
const tenant = useTenant()
const timeZone = computed(() => tenant.value?.timezone)

const statusOptions: { label: string; value: TicketStatus }[] = [
  { label: 'Новые', value: 'submitted' },
  { label: 'В работе', value: 'in_progress' },
  { label: 'Решённые', value: 'resolved' },
]
</script>

<template>
  <div class="stack">
    <PageHeading
      title="Тикеты"
      subtitle="Обращения арендаторов о неполадках"
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
    <TicketQueue
      v-else
      :tickets="data?.items ?? []"
      :loading="pending"
      :pending="updating"
      :time-zone="timeZone"
      @apply="update"
    />
  </div>
</template>
