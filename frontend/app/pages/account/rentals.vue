<script setup lang="ts">
import type { Rental } from '~/entities/rental'
import { ReportIssueDialog } from '~/features/ticket-create'
import { useCancelRental } from '~/features/rental-cancel'
import { useRentals } from '~/features/rental-list'
import { ErrorState, PageHeading } from '~/shared/ui'
import { RentalList } from '~/widgets/rental-list'

definePageMeta({ middleware: ['auth', 'not-staff'] })

const { data, pending, error, refresh } = await useRentals()
const { cancel } = useCancelRental()

const reportRental = ref<Rental | null>(null)
const reportVisible = computed({
  get: () => reportRental.value !== null,
  set: (value: boolean) => {
    if (!value) {
      reportRental.value = null
    }
  },
})

const onCancel = async (id: string) => {
  if (await cancel(id)) {
    await refresh()
  }
}

const onReport = (id: string) => {
  reportRental.value = data.value?.items.find(rental => rental.id === id) ?? null
}

const onTicketCreated = async () => {
  await refresh()
}
</script>

<template>
  <div class="stack">
    <PageHeading
      title="Мои аренды"
      subtitle="Активные брони и история"
    />

    <ErrorState
      v-if="error"
      :error="error"
      @retry="refresh"
    />
    <RentalList
      v-else
      :rentals="data?.items ?? []"
      :loading="pending"
      @cancel="onCancel"
      @report="onReport"
    />
  </div>

  <ReportIssueDialog
    v-if="reportRental"
    v-model:visible="reportVisible"
    :rental="reportRental"
    @created="onTicketCreated"
  />
</template>
