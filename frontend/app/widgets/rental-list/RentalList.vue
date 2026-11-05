<script setup lang="ts">
import { RentalCard, type Rental } from '~/entities/rental'
import { useTenant } from '~/entities/tenant'
import { EmptyState } from '~/shared/ui'

withDefaults(defineProps<{ rentals: Rental[]; loading?: boolean; pendingId?: string | null }>(), {
  loading: false,
  pendingId: null,
})

const emit = defineEmits<{ cancel: [id: string] }>()

const tenant = useTenant()
const timeZone = computed(() => tenant.value?.timezone)
</script>

<template>
  <div
    v-if="loading"
    class="stack"
  >
    <Skeleton
      v-for="index in 2"
      :key="index"
      height="180px"
      border-radius="16px"
    />
  </div>

  <EmptyState
    v-else-if="rentals.length === 0"
    title="Аренд пока нет"
    description="Выберите лот в каталоге и забронируйте удобный интервал"
  />

  <div
    v-else
    class="stack"
  >
    <RentalCard
      v-for="rental in rentals"
      :key="rental.id"
      :rental="rental"
      :time-zone="timeZone"
      @cancel="emit('cancel', $event)"
    />
  </div>
</template>
