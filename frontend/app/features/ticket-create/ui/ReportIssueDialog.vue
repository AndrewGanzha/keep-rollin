<script setup lang="ts">
import type { Rental } from '~/entities/rental'
import type { TicketCategory } from '~/entities/ticket'
import { useCreateTicket } from '../model/useCreateTicket'

const props = defineProps<{ rental: Rental }>()
const emit = defineEmits<{ created: [] }>()
const visible = defineModel<boolean>('visible', { required: true })

const { create, pending } = useCreateTicket()

const categoryOptions: { label: string; value: TicketCategory }[] = [
  { label: 'Не включается', value: 'no_power' },
  { label: 'Не едет', value: 'no_drive' },
  { label: 'Аккумулятор', value: 'battery' },
  { label: 'Повреждение', value: 'damage' },
  { label: 'Другое', value: 'other' },
]

const category = ref<TicketCategory | null>(null)
const description = ref('')

const length = computed(() => description.value.trim().length)
const valid = computed(() =>
  category.value !== null && length.value >= 10 && length.value <= 1000,
)

watch(visible, (open) => {
  if (open) {
    category.value = null
    description.value = ''
  }
})

const onConfirm = async () => {
  if (!valid.value || category.value === null) {
    return
  }

  const ticket = await create(props.rental.id, {
    category: category.value,
    description: description.value.trim(),
  })

  if (ticket) {
    visible.value = false
    emit('created')
  }
}
</script>

<template>
  <Dialog
    v-model:visible="visible"
    modal
    position="top"
    :header="`Неполадка: ${rental.lot.name}`"
    :style="{ width: '520px', maxWidth: '94vw', marginTop: '6vh' }"
  >
    <div class="stack">
      <Message
        severity="secondary"
        size="small"
        :closable="false"
      >
        Опишите проблему — заявку увидит администратор и свяжется с вами.
      </Message>

      <div class="field">
        <span class="field__label">Категория проблемы</span>
        <SelectButton
          v-model="category"
          :options="categoryOptions"
          option-label="label"
          option-value="value"
          aria-label="Категория проблемы"
        />
      </div>

      <div class="field">
        <label for="ticket-description">Описание</label>
        <Textarea
          id="ticket-description"
          v-model="description"
          rows="4"
          auto-resize
          placeholder="Что случилось и при каких обстоятельствах"
          fluid
        />
        <small
          class="muted"
          :class="{ 'text-error': length > 0 && length < 10 }"
        >
          {{ length }}/1000{{ length < 10 ? ' — минимум 10 символов' : '' }}
        </small>
      </div>
    </div>

    <template #footer>
      <Button
        label="Отмена"
        text
        @click="visible = false"
      />
      <Button
        label="Отправить"
        :disabled="!valid"
        :loading="pending"
        @click="onConfirm"
      />
    </template>
  </Dialog>
</template>

<style scoped>
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

.text-error {
  color: var(--p-red-500);
}

:deep(.p-selectbutton) {
  flex-wrap: wrap;
}
</style>
