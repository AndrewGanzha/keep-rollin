<script setup lang="ts">
import { formatDateTime, formatDuration, formatMoney } from '~/shared/lib'
import type { Rental } from '../model/rental.types'
import { rentalStatusLabels, rentalStatusSeverity } from '../model/rental.status'

withDefaults(defineProps<{ rental: Rental; timeZone?: string }>(), { timeZone: undefined })
const emit = defineEmits<{ cancel: [id: string]; report: [id: string] }>()

const canCancel = (rental: Rental): boolean =>
  rental.status === 'booked'
  && (!rental.cancellation_deadline || new Date(rental.cancellation_deadline) > new Date())

const canReport = (rental: Rental): boolean => rental.status === 'active'
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
          :severity="rentalStatusSeverity[rental.status]"
          :value="rentalStatusLabels[rental.status]"
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
      <div
        class="row"
        style="justify-content: space-between"
      >
        <div class="row">
          <Button
            v-if="canReport(rental)"
            label="Сообщить о неполадке"
            severity="warn"
            size="small"
            outlined
            @click="emit('report', rental.id)"
          />
          <Button
            v-if="canCancel(rental)"
            label="Отменить"
            severity="danger"
            text
            size="small"
            @click="emit('cancel', rental.id)"
          />
        </div>
        <NuxtLink
          v-if="!canCancel(rental) || canReport(rental)"
          :to="`/lots/${rental.lot.slug}`"
        >
          <Button
            label="К лоту"
            size="small"
            outlined
          />
        </NuxtLink>
      </div>
    </template>
  </Card>
</template>
