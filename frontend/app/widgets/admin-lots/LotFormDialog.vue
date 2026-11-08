<script setup lang="ts">
import type { Category } from '~/entities/category'
import type { CreateLotRequest, Lot } from '~/entities/lot'

const props = withDefaults(
  defineProps<{ categories: Category[]; pending?: boolean }>(),
  { pending: false },
)

const emit = defineEmits<{ submit: [payload: CreateLotRequest] }>()
const visible = defineModel<boolean>('visible', { required: true })

type RentalModel = Lot['rental_model']
type LotStatus = NonNullable<CreateLotRequest['status']>

const name = ref('')
const description = ref('')
const categoryId = ref<string | null>(null)
const rentalModel = ref<RentalModel>('daily')
const priceText = ref('')
const photosText = ref('')
const status = ref<LotStatus>('active')
const values = ref<Record<string, string | number>>({})

const modelOptions: { label: string; value: RentalModel }[] = [
  { label: 'Посуточно', value: 'daily' },
  { label: 'По часам', value: 'hourly' },
  { label: 'Индивидуально', value: 'custom' },
]

const statusOptions: { label: string; value: LotStatus }[] = [
  { label: 'Активен', value: 'active' },
  { label: 'Обслуживание', value: 'maintenance' },
  { label: 'Архив', value: 'archived' },
]

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

const canSubmit = computed(() =>
  name.value.trim().length >= 2
  && Boolean(categoryId.value)
  && Number(priceText.value) > 0
  && missingRequired.value.length === 0,
)

const priceHint = computed(() => {
  if (rentalModel.value === 'hourly') {
    return 'за час'
  }

  return rentalModel.value === 'daily' ? 'за сутки' : 'по договору'
})

const valueOf = (code: string): string | number => values.value[code] ?? ''

const setValue = (code: string, value: string | number | null | undefined) => {
  values.value = { ...values.value, [code]: value ?? '' }
}

const reset = () => {
  name.value = ''
  description.value = ''
  rentalModel.value = 'daily'
  priceText.value = ''
  photosText.value = ''
  status.value = 'active'
  values.value = {}
  categoryId.value = props.categories[0]?.id ?? null
}

watch(visible, (open) => {
  if (open) {
    reset()
  }
})

watch(categoryId, () => {
  values.value = {}
})

watch(() => props.categories.length, () => {
  if (visible.value && !categoryId.value) {
    categoryId.value = props.categories[0]?.id ?? null
  }
})

const submit = () => {
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
    rental_model: rentalModel.value,
    price_minor: Math.round(Number(priceText.value) * 100),
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
    header="Новый лот"
    :style="{ width: '640px', maxWidth: '94vw' }"
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
        <small class="muted">Slug сгенерируется автоматически</small>
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
        <span class="field__label">Модель аренды</span>
        <SelectButton
          v-model="rentalModel"
          :options="modelOptions"
          option-label="label"
          option-value="value"
          :allow-empty="false"
          aria-label="Модель аренды"
        />
      </div>

      <div class="field">
        <label for="lot-price">Цена, ₽ {{ priceHint }}</label>
        <InputText
          id="lot-price"
          v-model="priceText"
          inputmode="decimal"
          placeholder="Например, 2000"
          fluid
        />
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
      </div>

      <div class="field">
        <label for="lot-status">Статус после создания</label>
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
        label="Создать лот"
        :disabled="!canSubmit"
        :loading="pending"
        @click="submit"
      />
    </template>
  </Dialog>
</template>

<style scoped>
.form-body {
  max-height: 66vh;
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

:deep(.p-selectbutton) {
  flex-wrap: wrap;
}
</style>
