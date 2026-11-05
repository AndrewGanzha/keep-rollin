<script setup lang="ts">
import { useCancelRental } from '~/features/rental-cancel'
import { useRentals } from '~/features/rental-list'
import { ErrorState, PageHeading } from '~/shared/ui'
import { RentalList } from '~/widgets/rental-list'

definePageMeta({ middleware: 'auth' })

const { data, pending, error, refresh } = await useRentals()
const { cancel } = useCancelRental()

const onCancel = async (id: string) => {
  if (await cancel(id)) {
    await refresh()
  }
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
    />
  </div>
</template>
