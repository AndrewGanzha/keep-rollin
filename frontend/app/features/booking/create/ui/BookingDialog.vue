<script setup lang="ts">
import type { Lot } from '~/entities/lot'
import { formatDateTime, formatMoney } from '~/shared/lib'
import { addUnits, durationOptions, durationText } from '../model/booking'
import { defaultVariantId, quoteOptions } from '../model/quote'
import { useCreateRental } from '../model/useCreateRental'
import { useQuote } from '../model/useQuote'

const props = defineProps<{ lot: Lot }>()
const visible = defineModel<boolean>('visible', { required: true })

const { create, pending } = useCreateRental()

const isHourly = computed(() => props.lot.rental_unit === 'hour')
const minUnits = computed(() => props.lot.allowed_durations[0] ?? 1)
const options = computed(() => durationOptions(props.lot.rental_unit, props.lot.allowed_durations))
const maxCustomUnits = computed(() => (isHourly.value ? 90 : 365))

const defaultStart = () => new Date(Math.ceil(Date.now() / 3600000) * 3600000)

const start = ref<Date | null>(defaultStart())
const duration = ref(minUnits.value)
const customUnits = ref(minUnits.value)

const units = computed(() => Math.max(duration.value === 0 ? customUnits.value : duration.value, minUnits.value))
const end = computed(() => (start.value ? addUnits(start.value, units.value, props.lot.rental_unit) : null))

const lotRef = toRef(props, 'lot')
const { quote, pending: quotePending, error: quoteError, refresh: refreshQuote } = useQuote(
  lotRef,
  start,
  end,
  visible,
)

const variantOptions = computed(() => quoteOptions(quote.value))
const selectedVariantId = ref('')

watch(variantOptions, (list) => {
  if (!list.some(option => option.value === selectedVariantId.value && !option.disabled)) {
    selectedVariantId.value = defaultVariantId(list)
  }
}, { immediate: true })

const selectedVariant = computed(() =>
  quote.value?.variants.find(variant => variant.variant_id === selectedVariantId.value) ?? null,
)
const disabledOptions = computed(() => variantOptions.value.filter(option => option.disabled))
const price = computed(() => selectedVariant.value?.price_total_minor ?? null)
const unitLabel = computed(() => durationText(units.value, props.lot.rental_unit))
const quoteErrorText = computed(() => quoteError.value?.code === 'rental_period_not_allowed'
  ? `Минимальный срок аренды — ${minUnits.value} ${isHourly.value ? 'ч' : 'сут.'}`
  : 'Не удалось рассчитать цену')

const valid = computed(() =>
  start.value !== null
  && end.value !== null
  && selectedVariant.value?.available === true
  && start.value.getTime() > Date.now() - 5 * 60 * 1000,
)

const reset = () => {
  start.value = defaultStart()
  duration.value = minUnits.value
  customUnits.value = minUnits.value
}

watch(visible, (open) => {
  if (open) {
    reset()
  }
})

watch([minUnits, isHourly], () => {
  if (visible.value) {
    reset()
  }
})

const onConfirm = async () => {
  if (!start.value || !end.value || !selectedVariantId.value || !valid.value) {
    return
  }

  const rental = await create(
    props.lot.id,
    selectedVariantId.value,
    { start: start.value, end: end.value },
    (code) => {
      if (code === 'slot_taken' || code === 'battery_unavailable') {
        void refreshQuote()
      }
    },
  )

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
    :style="{ width: '560px', maxWidth: '94vw', marginTop: '6vh' }"
  >
    <div class="stack">
      <div class="field">
        <span class="field__label">Комплектация</span>
        <div
          v-if="quotePending && variantOptions.length === 0"
          class="muted"
        >
          Считаем стоимость…
        </div>
        <SelectButton
          v-else
          v-model="selectedVariantId"
          :options="variantOptions"
          option-label="label"
          option-value="value"
          :option-disabled="(option) => option.disabled"
          :allow-empty="false"
          aria-label="Комплектация"
        >
          <template #option="{ option }">
            <span class="variant">
              <strong>{{ option.label }}</strong>
              <small>{{ option.price }}</small>
            </span>
          </template>
        </SelectButton>
        <ul
          v-if="disabledOptions.length > 0"
          class="booking__reasons muted"
        >
          <li
            v-for="option in disabledOptions"
            :key="option.value"
          >
            {{ option.label }} — {{ option.reason }}
          </li>
        </ul>
      </div>

      <div class="stack booking__price">
        <span class="booking__amount">{{ price === null ? '—' : formatMoney(price, lot.currency) }}</span>
        <span
          v-if="quote"
          class="muted"
        >
          за {{ unitLabel }} · тариф от {{ selectedVariant?.tier_min_units }} {{ isHourly ? 'ч' : 'сут.' }}
        </span>
      </div>

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
            :min="minUnits"
            :max="maxCustomUnits"
            :suffix="isHourly ? ' ч' : ' дн.'"
            show-buttons
            fluid
          />
          <span class="muted">Минимум {{ minUnits }} {{ isHourly ? 'ч' : 'дн.' }}</span>
        </div>
      </div>

      <div
        v-if="start && end"
        class="booking__summary"
      >
        <span class="muted">Интервал</span>
        <strong>{{ formatDateTime(start.toISOString()) }} — {{ formatDateTime(end.toISOString()) }}</strong>
        <span class="muted">Стоимость</span>
        <strong>{{ price === null ? '—' : formatMoney(price, lot.currency) }}</strong>
      </div>

      <Message
        v-if="quoteError"
        severity="error"
        :closable="false"
      >
        {{ quoteErrorText }}
      </Message>

      <small class="muted">
        Цену и доступность считает сервер; при бронировании стоимость фиксируется.
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
  font-size: 1.5rem;
  font-weight: 700;
}

.booking__reasons {
  margin: 0;
  padding-left: 18px;
  font-size: 0.85rem;
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

.variant {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  line-height: 1.2;
}

.variant small {
  font-size: 0.75rem;
  opacity: 0.8;
}

:deep(.p-selectbutton) {
  flex-wrap: wrap;
}
</style>
