<script setup lang="ts">
import { useTenant } from '~/entities/tenant'
import { useMyTickets } from '~/features/ticket-list'
import { ErrorState, PageHeading } from '~/shared/ui'
import { TicketList } from '~/widgets/ticket-list'

definePageMeta({ middleware: ['auth', 'not-staff'] })

useHead({ title: 'Мои обращения' })

const { data, pending, error, refresh } = await useMyTickets()
const tenant = useTenant()
const timeZone = computed(() => tenant.value?.timezone)
</script>

<template>
  <div class="stack">
    <PageHeading
      title="Мои обращения"
      subtitle="Заявки о неполадках и ответы администратора"
    />

    <ErrorState
      v-if="error"
      :error="error"
      @retry="refresh"
    />
    <TicketList
      v-else
      :tickets="data?.items ?? []"
      :loading="pending"
      :time-zone="timeZone"
    />
  </div>
</template>
