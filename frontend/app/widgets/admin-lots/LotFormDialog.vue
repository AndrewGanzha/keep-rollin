<script setup lang="ts">
import type { Category } from '~/entities/category'
import { type CreateLotRequest, type Lot } from '~/entities/lot'

const props = withDefaults(
  defineProps<{
    categories: Category[]
    pending?: boolean
    lot?: Lot | null
    errors?: Record<string, string>
  }>(),
  { pending: false, lot: null, errors: () => ({}) },
)

const emit = defineEmits<{ submit: [payload: CreateLotRequest] }>()
const visible = defineModel<boolean>('visible', { required: true })

type LotStatus = NonNullable<CreateLotRequest['status']>
type RentalUnit = Lot['rental_unit']

interface TierForm {
  min_units: number
  price_rub: number
}

interface VariantForm {
  battery_count: number
  tiers: TierForm[]
}

const DURATION_PRESETS = [1, 3, 7, 30]

const name = ref('')
const description = ref('')
const categoryId = ref<string | null>(null)
const rentalUnit = ref<RentalUnit>('day')
const batteryType = ref('48v')
const allowed = ref<number[]>([...DURATION_PRESETS])
const status = ref<LotStatus>('active')
const photosText = ref('')
const values = ref<Record<string, string | number>>({})
const variants = ref<VariantForm[]>([])
const attempted = ref(false)

const statusOptions: { label: string; value: LotStatus }[] = [
  { label: 'Активен', value: 'active' },
  { label: 'Обслуживание', value: 'maintenance' },
  { label: 'Архив', value: 'archived' },
]

const batteryOptions = [
  { label: 'Без АКБ', value: 0 },
  { label: '1 АКБ', value: 1 },
  { label: '2 АКБ', value: 2 },
]

const unitLabel = computed(() => (rentalUnit.value === 'hour' ? 'час' : 'сутки'))
const unitShort = computed(() => (rentalUnit.value === 'hour' ? 'ч' : 'дн.'))

const selectedCategory = computed(() =>
  props.categories.find(item => item.id === categoryId.value) ?? null,
)

const characteristics = computed(() =>
  (selectedCategory.value?.characteristics ?? [])
    .slice()
    .sort((left, right) => left.sort - right.sort),
)

const missingRequired = computed(() =>
  characteristics.value.filter(item =>
    item.is_required && (values.value[item.code] === undefined || values.value[item.code] === ''),
  ),
)

const minAllowed = computed(() => allowed.value[0] ?? 1)
const durationPresets = computed(() =>
  Array.from(new Set([...DURATION_PRESETS, ...allowed.value])).sort((left, right) => left - right),
)
const hasBattery = computed(() => variants.value.some(variant => variant.battery_count > 0))

const defaultTiers = (): TierForm[] => {
  const units = [...allowed.value].sort((left, right) => left - right)

  return units.slice(0, 3).map(min_units => ({ min_units, price_rub: 0 }))
}

const makeVariant = (batteryCount: number): VariantForm => ({
  battery_count: batteryCount,
  tiers: defaultTiers(),
})

const reset = () => {
  name.value = ''
  description.value = ''
  rentalUnit.value = 'day'
  batteryType.value = '48v'
  allowed.value = [...DURATION_PRESETS]
  status.value = 'active'
  photosText.value = ''
  values.value = {}
  variants.value = [makeVariant(1)]
  categoryId.value = props.categories[0]?.id ?? null
}

const fill = (lot: Lot) => {
  name.value = lot.name
  description.value = lot.description ?? ''
  categoryId.value = lot.category_id
  rentalUnit.value = lot.rental_unit
  batteryType.value = lot.battery_type ?? '48v'
  allowed.value = [...lot.allowed_durations]
  status.value = lot.status === 'overdue' ? 'maintenance' : lot.status
  photosText.value = lot.photos.join('\n')
  values.value = { ...lot.characteristics }
  variants.value = lot.variants.map(variant => ({
    battery_count: variant.battery_count,
    tiers: variant.price_tiers.map(tier => ({
      min_units: tier.min_units,
      price_rub: tier.price_per_unit_minor / 100,
    })),
  }))
}

watch(visible, (open) => {
  if (!open) {
    return
  }

  attempted.value = false

  if (props.lot) {
    fill(props.lot)
  } else {
    reset()
  }
})

watch(minAllowed, (minimum) => {
  variants.value = variants.value.map(variant => ({
    ...variant,
    tiers: variant.tiers.map((tier, index) =>
      index === 0 ? { ...tier, min_units: minimum } : tier,
    ),
  }))
})

watch(categoryId, () => {
  values.value = {}
}, { flush: 'sync' })

watch(() => props.categories.length, () => {
  if (visible.value && !categoryId.value) {
    categoryId.value = props.categories[0]?.id ?? null
  }
})

const toggleDuration = (value: number, checked: boolean | undefined) => {
  allowed.value = checked
    ? [...allowed.value, value].sort((left, right) => left - right)
    : allowed.value.filter(item => item !== value)
}

const addVariant = () => {
  if (variants.value.length >= 2) {
    return
  }

  const used = new Set(variants.value.map(variant => variant.battery_count))
  const next = [1, 2].find(count => !used.has(count)) ?? 2
  variants.value = [...variants.value, makeVariant(next)]
}

const removeVariant = (index: number) => {
  if (variants.value.length > 1) {
    variants.value = variants.value.filter((_, itemIndex) => itemIndex !== index)
  }
}

const addTier = (variantIndex: number) => {
  const variant = variants.value[variantIndex]

  if (!variant) {
    return
  }

  const last = variant.tiers[variant.tiers.length - 1]
  const nextUnit = durationPresets.value.find(unit => unit > (last?.min_units ?? 0)) ?? minAllowed.value
  variant.tiers = [...variant.tiers, { min_units: nextUnit, price_rub: last?.price_rub ?? 0 }]
}

const removeTier = (variantIndex: number, tierIndex: number) => {
  const variant = variants.value[variantIndex]

  if (variant && variant.tiers.length > 1) {
    variant.tiers = variant.tiers.filter((_, index) => index !== tierIndex)
  }
}

const variantErrors = computed<Record<number, string>>(() => {
  const result: Record<number, string> = {}
  const counts = new Set<number>()

  variants.value.forEach((variant, index) => {
    if (counts.has(variant.battery_count)) {
      result[index] = 'Вариант с таким количеством АКБ уже есть'
    }

    counts.add(variant.battery_count)

    if (variant.tiers.length === 0) {
      result[index] = 'Добавьте хотя бы один тариф'
      return
    }

    if (variant.tiers[0]?.min_units !== minAllowed.value) {
      result[index] = `Первый тариф должен начинаться с ${minAllowed.value} ${unitShort.value}`
      return
    }

    let previousUnits = 0
    let previousPrice = Number.POSITIVE_INFINITY

    for (const tier of variant.tiers) {
      if (tier.min_units <= previousUnits) {
        result[index] = 'Сроки тарифов должны возрастать'
        return
      }

      if (tier.price_rub <= 0 || tier.price_rub > previousPrice) {
        result[index] = 'Цена за единицу не должна расти со сроком'
        return
      }

      previousUnits = tier.min_units
      previousPrice = tier.price_rub
    }
  })

  return result
})

const localErrors = computed<Record<string, string>>(() => {
  const errors: Record<string, string> = {}

  if (name.value.trim().length < 2) {
    errors.name = 'Минимум 2 символа'
  }

  if (!categoryId.value) {
    errors.category_id = 'Выберите категорию'
  }

  if (allowed.value.length === 0) {
    errors.allowed_durations = 'Оставьте хотя бы один срок'
  }

  if (hasBattery.value && !batteryType.value) {
    errors.battery_type = 'Выберите тип АКБ'
  }

  if (missingRequired.value.length > 0) {
    errors.characteristics = `Заполните: ${missingRequired.value.map(item => item.name).join(', ')}`
  }

  if (variants.value.length === 0) {
    errors.variants = 'Нужен хотя бы один вариант'
  }

  for (const [index, message] of Object.entries(variantErrors.value)) {
    errors[`variants.${index}`] = message
  }

  return errors
})

const canSubmit = computed(() => Object.keys(localErrors.value).length === 0)

const errorFor = (path: string): string =>
  props.errors[path] ?? (attempted.value ? localErrors.value[path] ?? '' : '')

const valueOf = (code: string): string | number => values.value[code] ?? ''

const setValue = (code: string, value: string | number | null | undefined) => {
  values.value = { ...values.value, [code]: value ?? '' }
}

const submit = () => {
  attempted.value = true

  if (!canSubmit.value || !categoryId.value) {
    return
  }

  const payloadCharacteristics: Record<string, string | number> = {}

  for (const item of characteristics.value) {
    const raw = values.value[item.code]

    if (raw === undefined || raw === '') {
      continue
    }

    payloadCharacteristics[item.code] = item.type === 'number' ? Number(raw) : raw
  }

  emit('submit', {
    name: name.value.trim(),
    category_id: categoryId.value,
    description: description.value.trim(),
    rental_unit: rentalUnit.value,
    battery_type: hasBattery.value ? batteryType.value || null : null,
    variants: variants.value.map(variant => ({
      battery_count: variant.battery_count,
      is_active: true,
      price_tiers: [...variant.tiers]
        .sort((left, right) => left.min_units - right.min_units)
        .map(tier => ({
          min_units: tier.min_units,
          price_per_unit_minor: Math.round(tier.price_rub * 100),
        })),
    })),
    allowed_durations: [...allowed.value].sort((left, right) => left - right),
    characteristics: payloadCharacteristics,
    photos: photosText.value
      .split('\n')
      .map(line => line.trim())
      .filter(Boolean),
    status: status.value,
  })
}
</script>

<template>
  <Dialog
    v-model:visible="visible"
    modal
    :header="lot ? 'Редактировать лот' : 'Новый лот'"
    :style="{ width: '720px', maxWidth: '96vw' }"
  >
    <div class="stack form-body">
      <div class="field">
        <label for="lot-name">Название</label>
        <InputText
          id="lot-name"
          v-model="name"
          placeholder="Например, Urban Three"
          maxlength="120"
          fluid
        />
        <small
          v-if="errorFor('name')"
          class="form-error"
        >{{ errorFor('name') }}</small>
      </div>

      <div class="field">
        <label for="lot-category">Категория</label>
        <Select
          id="lot-category"
          v-model="categoryId"
          :options="categories"
          option-label="name"
          option-value="id"
          placeholder="Выберите категорию"
          fluid
        />
        <small
          v-if="errorFor('category_id')"
          class="form-error"
        >{{ errorFor('category_id') }}</small>
      </div>

      <div class="field">
        <label for="lot-description">Описание</label>
        <Textarea
          id="lot-description"
          v-model="description"
          rows="2"
          auto-resize
          maxlength="1000"
          fluid
        />
      </div>

      <div class="field">
        <span class="field__label">Единица срока</span>
        <SelectButton
          v-model="rentalUnit"
          :options="[
            { label: 'Сутки', value: 'day' },
            { label: 'Часы', value: 'hour' },
          ]"
          option-label="label"
          option-value="value"
          :allow-empty="false"
          aria-label="Единица срока"
        />
        <small
          v-if="errorFor('rental_unit')"
          class="form-error"
        >{{ errorFor('rental_unit') }}</small>
      </div>

      <div class="field">
        <span class="field__label">Разрешённые сроки, {{ unitShort }}</span>
        <div class="row durations">
          <label
            v-for="duration in durationPresets"
            :key="duration"
            class="duration"
          >
            <Checkbox
              :model-value="allowed.includes(duration)"
              binary
              @update:model-value="toggleDuration(duration, $event)"
            />
            <span>{{ duration }}</span>
          </label>
        </div>
        <small class="muted">Минимальный срок — {{ minAllowed }} {{ unitShort }}; первый тариф начинается с него.</small>
        <small
          v-if="errorFor('allowed_durations')"
          class="form-error"
        >{{ errorFor('allowed_durations') }}</small>
      </div>

      <div
        v-if="hasBattery"
        class="field"
      >
        <label for="lot-battery">Тип АКБ</label>
        <Select
          id="lot-battery"
          v-model="batteryType"
          :options="[
            { label: '48V', value: '48v' },
            { label: '36V', value: '36v' },
          ]"
          option-label="label"
          option-value="value"
          fluid
        />
        <small
          v-if="errorFor('battery_type')"
          class="form-error"
        >{{ errorFor('battery_type') }}</small>
      </div>

      <div class="stack">
        <div class="row variants-head">
          <span class="field__label">Варианты и тарифы</span>
          <Button
            label="+ вариант"
            size="small"
            text
            :disabled="variants.length >= 2"
            @click="addVariant"
          />
        </div>

        <div
          v-for="(variant, variantIndex) in variants"
          :key="variantIndex"
          class="variant-card"
        >
          <div class="row variant-head">
            <div
              class="field"
              style="max-width: 180px"
            >
              <label :for="`variant-bc-${variantIndex}`">АКБ</label>
              <Select
                :id="`variant-bc-${variantIndex}`"
                v-model="variant.battery_count"
                :options="batteryOptions"
                option-label="label"
                option-value="value"
                fluid
              />
              <small
                v-if="errorFor(`variants.${variantIndex}.battery_count`)"
                class="form-error"
              >{{ errorFor(`variants.${variantIndex}.battery_count`) }}</small>
            </div>
            <Button
              v-if="variants.length > 1"
              icon="pi pi-trash"
              text
              severity="danger"
              aria-label="Удалить вариант"
              @click="removeVariant(variantIndex)"
            />
          </div>

          <div
            v-for="(tier, tierIndex) in variant.tiers"
            :key="tierIndex"
            class="tier-row"
          >
            <div class="field">
              <label>Срок, {{ unitShort }}</label>
              <InputNumber
                v-model="tier.min_units"
                :min="1"
                :max="365"
                show-buttons
                fluid
              />
              <small
                v-if="errorFor(`variants.${variantIndex}.price_tiers.${tierIndex}.min_units`)"
                class="form-error"
              >{{ errorFor(`variants.${variantIndex}.price_tiers.${tierIndex}.min_units`) }}</small>
            </div>
            <div class="field">
              <label>Цена за {{ unitLabel }}, ₽</label>
              <InputNumber
                v-model="tier.price_rub"
                :min="1"
                :max="1000000"
                :step="50"
                fluid
              />
              <small
                v-if="errorFor(`variants.${variantIndex}.price_tiers.${tierIndex}.price_per_unit_minor`)"
                class="form-error"
              >{{ errorFor(`variants.${variantIndex}.price_tiers.${tierIndex}.price_per_unit_minor`) }}</small>
            </div>
            <Button
              v-if="variant.tiers.length > 1"
              icon="pi pi-times"
              text
              aria-label="Удалить тариф"
              @click="removeTier(variantIndex, tierIndex)"
            />
          </div>

          <small
            v-if="errorFor(`variants.${variantIndex}`)"
            class="form-error"
          >{{ errorFor(`variants.${variantIndex}`) }}</small>

          <Button
            label="Добавить тариф"
            size="small"
            text
            icon="pi pi-plus"
            @click="addTier(variantIndex)"
          />
        </div>
      </div>

      <div
        v-if="characteristics.length > 0"
        class="stack"
      >
        <span class="field__label">Характеристики</span>
        <div
          v-for="item in characteristics"
          :key="item.id"
          class="field"
        >
          <label :for="`char-${item.code}`">
            {{ item.name }}<span
              v-if="item.is_required"
              class="required"
            > *</span>
          </label>

          <InputText
            v-if="item.type === 'number'"
            :id="`char-${item.code}`"
            :model-value="String(valueOf(item.code))"
            inputmode="decimal"
            :placeholder="item.unit ? `Значение, ${item.unit}` : 'Значение'"
            fluid
            @update:model-value="setValue(item.code, $event)"
          />
          <Select
            v-else-if="item.type === 'select'"
            :id="`char-${item.code}`"
            :model-value="String(valueOf(item.code))"
            :options="item.options"
            fluid
            @update:model-value="setValue(item.code, $event)"
          />
          <InputText
            v-else
            :id="`char-${item.code}`"
            :model-value="String(valueOf(item.code))"
            fluid
            @update:model-value="setValue(item.code, $event)"
          />
        </div>
        <small
          v-if="errorFor('characteristics')"
          class="form-error"
        >{{ errorFor('characteristics') }}</small>
      </div>

      <div class="field">
        <label for="lot-photos">Фотографии</label>
        <Textarea
          id="lot-photos"
          v-model="photosText"
          rows="2"
          placeholder="По одной ссылке в строке"
          fluid
        />
        <small
          v-if="errorFor('photos')"
          class="form-error"
        >{{ errorFor('photos') }}</small>
      </div>

      <div class="field">
        <label for="lot-status">Статус</label>
        <Select
          id="lot-status"
          v-model="status"
          :options="statusOptions"
          option-label="label"
          option-value="value"
          fluid
        />
      </div>
    </div>

    <template #footer>
      <Button
        label="Отмена"
        text
        @click="visible = false"
      />
      <Button
        :label="lot ? 'Сохранить' : 'Создать лот'"
        :loading="pending"
        @click="submit"
      />
    </template>
  </Dialog>
</template>

<style scoped>
.form-body {
  max-height: 70vh;
  overflow-y: auto;
  padding-right: 4px;
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

.required {
  color: var(--p-red-500);
}

.form-error {
  color: var(--p-red-500);
  font-size: 0.8rem;
}

.durations {
  flex-wrap: wrap;
  gap: 12px;
}

.duration {
  display: flex;
  align-items: center;
  gap: 6px;
}

.variants-head,
.variant-head {
  align-items: center;
  justify-content: space-between;
}

.variant-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px;
  border: 1px solid var(--p-content-border-color);
  border-radius: var(--p-content-border-radius);
}

.tier-row {
  display: grid;
  grid-template-columns: 110px minmax(140px, 1fr) auto;
  gap: 8px;
  align-items: end;
}

:deep(.p-selectbutton) {
  flex-wrap: wrap;
}
</style>
