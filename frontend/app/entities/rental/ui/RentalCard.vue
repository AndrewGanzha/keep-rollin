<script setup lang="ts">
import { formatDateTime, formatDuration, formatMoney } from '~/shared/lib'
import type { Rental, RentalStatus } from '../model/rental.types'

withDefaults(defineProps<{ rental: Rental; timeZone?: string }>(), { timeZone: undefined })
const emit = defineEmits<{ cancel: [id: string] }>()

const severity: Record<RentalStatus, 'success' | 'info' | 'warn' | 'danger' | 'secondary'> = {
  booked: 'info',
  active: 'success',
  overdue: 'danger',
  completed: 'secondary',
  cancelled: 'secondary',
}

const labels: Record<RentalStatus, string> = {
  booked: 'Забронировано',
  active: 'Активна',
  overdue: 'Просрочена',
  completed: 'Завершена',
  cancelled: 'Отменена',
}

const canCancel = (rental: Rental): boolean =>
  rental.status === 'booked'
  && (!rental.cancellation_deadline || new Date(rental.cancellation_deadline) > new Date())
</script>

<template>
  <Card>
    <template #title>
      <div
        class="row"
        style="justify-content: space-between"
      >
        <span>{{ rental.lot.name }}</span>
        <Tag
          :severity="severity[rental.status]"
          :value="labels[rental.status]"
        />
      </div>
    </template>

    <template #content>
      <div
        class="stack"
        style="gap: 6px"
      >
        <span class="muted">{{ formatDateTime(rental.start_time, timeZone) }} — {{ formatDateTime(rental.end_time, timeZone) }}</span>
        <span>{{ formatMoney(rental.price_minor, rental.currency) }}</span>
        <span
          v-if="rental.status === 'active'"
          class="muted"
        >
          Осталось: {{ formatDuration(rental.remaining_seconds) }}
        </span>
      </div>
    </template>

    <template #footer>
      <Button
        v-if="canCancel(rental)"
        label="Отменить"
        severity="danger"
        text
        size="small"
        @click="emit('cancel', rental.id)"
      />
      <NuxtLink
        v-else
        :to="`/lots/${rental.lot.slug}`"
      >
        <Button
          label="К лоту"
          size="small"
          outlined
        />
      </NuxtLink>
    </template>
  </Card>
</template>
