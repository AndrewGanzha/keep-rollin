<script setup lang="ts">
import type { VerificationStatus } from '~/entities/verification'
import { useTenant } from '~/entities/tenant'
import { useVerificationQueue } from '~/features/admin-verification'
import { ErrorState, PageHeading } from '~/shared/ui'
import { VerificationQueue } from '~/widgets/admin-verification'

definePageMeta({ layout: 'admin', middleware: ['auth', 'role'] })

useHead({ title: 'Верификация — админка' })

const { data, pending, error, refresh, status, deciding, decide } = await useVerificationQueue()
const tenant = useTenant()
const timeZone = computed(() => tenant.value?.timezone)

const statusOptions: { label: string; value: VerificationStatus }[] = [
  { label: 'На проверке', value: 'pending' },
  { label: 'Одобрена', value: 'approved' },
  { label: 'Отклонена', value: 'rejected' },
]
</script>

<template>
  <div class="stack">
    <PageHeading
      title="Верификация"
      subtitle="Очередь заявок на проверку документов"
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
    <VerificationQueue
      v-else
      :requests="data?.items ?? []"
      :loading="pending"
      :pending="deciding"
      :time-zone="timeZone"
      @decide="decide"
    />
  </div>
</template>
