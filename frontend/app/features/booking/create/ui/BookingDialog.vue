<script setup lang="ts">
import type { Lot } from '~/entities/lot'
import { formatDateTime, formatMoney } from '~/shared/lib'
import { addUnits, durationOptions, estimatePrice, unitOf } from '../model/booking'
import { useCreateRental } from '../model/useCreateRental'

const props = defineProps<{ lot: Lot }>()
const visible = defineModel<boolean>('visible', { required: true })

const { create, pending } = useCreateRental()

const unit = computed(() => unitOf(props.lot.rental_model))
const isHourly = computed(() => unit.value === 'hour')
const options = computed(() => durationOptions(unit.value))

const defaultStart = () => new Date(Math.ceil(Date.now() / 3600000) * 3600000)

const start = ref<Date | null>(defaultStart())
const duration = ref(isHourly.value ? 24 : 1)
const customUnits = ref(1)

const units = computed(() => Math.max(duration.value === 0 ? customUnits.value : duration.value, 1))
const end = computed(() => (start.value ? addUnits(start.value, units.value, unit.value) : null))
const price = computed(() => estimatePrice(props.lot, units.value))
const valid = computed(() =>
  start.value !== null
  && units.value > 0
  && start.value.getTime() > Date.now() - 5 * 60 * 1000,
)

const unitSuffix = computed(() => (isHourly.value ? 'ч' : 'дн.'))
const priceSuffix = computed(() => (isHourly.value ? 'за час' : 'за сутки'))

watch(visible, (open) => {
  if (open) {
    start.value = defaultStart()
    duration.value = isHourly.value ? 24 : 1
    customUnits.value = 1
  }
})

const onConfirm = async () => {
  if (!start.value || !end.value || !valid.value) {
    return
  }

  const rental = await create(props.lot.id, { start: start.value, end: end.value })

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
    :style="{ width: '520px', maxWidth: '94vw', marginTop: '6vh' }"
  >
    <div class="stack">
      <div class="stack booking__price">
        <span class="booking__amount">{{ formatMoney(lot.price_minor, lot.currency) }}</span>
        <span class="muted">{{ priceSuffix }}</span>
      </div>

      <Message
        severity="secondary"
        size="small"
        :closable="false"
      >
        {{ isHourly
          ? 'Обычно лот берут от суток. При необходимости можно выбрать несколько часов.'
          : 'Аренда от 1 дня: на день, несколько дней, неделю или месяц.' }}
      </Message>

      <div class="field">
        <label for="booking-start">Начало аренды</label>
        <DatePicker
          id="booking-start"
          v-model="start"
          show-time
          hour-format="24"
          :min-date="new Date()"
          :manual-input="false"
          placeholder="Выберите дату и время"
          fluid
        />
      </div>

      <div class="field">
        <span class="field__label">Срок аренды</span>
        <SelectButton
          v-model="duration"
          :options="options"
          option-label="label"
          option-value="value"
          :allow-empty="false"
          aria-label="Срок аренды"
        />

        <div
          v-if="duration === 0"
          class="row"
        >
          <InputNumber
            v-model="customUnits"
            :min="1"
            :max="isHourly ? 168 : 90"
            :suffix="` ${unitSuffix}`"
            show-buttons
            fluid
          />
          <span class="muted">Например, {{ isHourly ? '6' : '10' }} {{ unitSuffix }}</span>
        </div>
      </div>

      <div
        v-if="start && end"
        class="booking__summary"
      >
        <span class="muted">Интервал</span>
        <strong>{{ formatDateTime(start.toISOString()) }} — {{ formatDateTime(end.toISOString()) }}</strong>
        <span class="muted">Ориентировочная стоимость</span>
        <strong>≈ {{ formatMoney(price, lot.currency) }}</strong>
      </div>

      <small class="muted">
        Точную стоимость и доступность подтвердит сервер при бронировании.
      </small>
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

<style scoped>
.booking__price {
  gap: 2px;
}

.booking__amount {
  font-size: 1.25rem;
  font-weight: 700;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.field label,
.field__label {
  font-size: 0.9rem;
  font-weight: 600;
}

.booking__summary {
  display: grid;
  gap: 4px 12px;
  padding: 10px 12px;
  border: 1px solid var(--p-content-border-color);
  border-radius: var(--p-content-border-radius);
  background: var(--p-content-background);
  font-size: 0.9rem;
}

.booking__summary strong {
  font-weight: 600;
}

:deep(.p-selectbutton) {
  flex-wrap: wrap;
}
</style>
