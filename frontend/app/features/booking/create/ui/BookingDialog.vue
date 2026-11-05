<script setup lang="ts">
import type { Lot } from '~/entities/lot'
import { formatMoney } from '~/shared/lib'
import { useCreateRental } from '../model/useCreateRental'

const props = defineProps<{ lot: Lot }>()
const visible = defineModel<boolean>('visible', { required: true })

const { create, pending } = useCreateRental()
const range = ref<Date[] | null>(null)

const minDate = new Date()

const valid = computed(() => {
  const [start, end] = range.value ?? []
  return Boolean(start && end && end > start)
})

const onConfirm = async () => {
  const [start, end] = range.value ?? []

  if (!start || !end) {
    return
  }

  const rental = await create(props.lot.id, { start, end })

  if (rental) {
    visible.value = false
  }
}
</script>

<template>
  <Dialog
    v-model:visible="visible"
    modal
    position="top"
    :header="`Бронь: ${lot.name}`"
    :style="{ width: '440px', maxWidth: '92vw', marginTop: '8vh' }"
  >
    <div class="stack">
      <p
        class="muted"
        style="margin: 0"
      >
        {{ formatMoney(lot.price_minor, lot.currency) }} · {{ lot.rental_model === 'hourly' ? 'за час' : 'за сутки' }}
      </p>

      <DatePicker
        v-model="range"
        selection-mode="range"
        show-time
        hour-format="24"
        :min-date="minDate"
        :manual-input="false"
        placeholder="Выберите интервал"
        fluid
      />

      <Message
        v-if="!valid && range"
        severity="warn"
        size="small"
        :closable="false"
      >
        Выберите начало и конец интервала
      </Message>
    </div>

    <template #footer>
      <Button
        label="Отмена"
        text
        @click="visible = false"
      />
      <Button
        label="Забронировать"
        :disabled="!valid"
        :loading="pending"
        @click="onConfirm"
      />
    </template>
  </Dialog>
</template>
