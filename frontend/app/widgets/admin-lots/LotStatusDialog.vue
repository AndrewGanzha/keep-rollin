<script setup lang="ts">
import type { Lot, LotStatusRequest } from '~/entities/lot'

const props = withDefaults(
  defineProps<{ lot: Lot | null; pending?: boolean }>(),
  { pending: false },
)

const emit = defineEmits<{
  'update:lot': [lot: Lot | null]
  confirm: [lot: Lot, status: LotStatusRequest['status']]
}>()

const next = ref<LotStatusRequest['status']>('active')

const options: { label: string; value: LotStatusRequest['status'] }[] = [
  { label: 'Активен', value: 'active' },
  { label: 'Обслуживание', value: 'maintenance' },
  { label: 'Архив', value: 'archived' },
]

const visible = computed({
  get: () => props.lot !== null,
  set: (value: boolean) => {
    if (!value) {
      emit('update:lot', null)
    }
  },
})

watch(() => props.lot, (lot) => {
  if (!lot) {
    return
  }

  next.value = lot.status === 'archived' || lot.status === 'maintenance' ? lot.status : 'active'
}, { immediate: true })

const canSubmit = computed(() => props.lot !== null && next.value !== props.lot.status)

const submit = () => {
  if (!props.lot || !canSubmit.value) {
    return
  }

  emit('confirm', props.lot, next.value)
}
</script>

<template>
  <Dialog
    v-model:visible="visible"
    modal
    header="Статус лота"
    :style="{ width: '420px', maxWidth: '92vw' }"
  >
    <div
      v-if="lot"
      class="stack"
    >
      <p style="margin: 0">
        {{ lot.name }} · <span class="muted">/{{ lot.slug }}</span>
      </p>

      <div class="field">
        <span class="field__label">Новый статус</span>
        <SelectButton
          v-model="next"
          :options="options"
          option-label="label"
          option-value="value"
          :allow-empty="false"
          aria-label="Статус лота"
        />
      </div>

      <Message
        v-if="next === 'archived'"
        severity="warn"
        size="small"
        :closable="false"
      >
        Архивировать лот с активными арендами нельзя — сервер вернёт ошибку.
      </Message>

      <Message
        v-else-if="next === 'maintenance'"
        severity="info"
        size="small"
        :closable="false"
      >
        Лот пропадёт из каталога и станет недоступен для новых броней.
      </Message>
    </div>

    <template #footer>
      <Button
        label="Отмена"
        text
        @click="visible = false"
      />
      <Button
        label="Применить"
        :disabled="!canSubmit"
        :loading="pending"
        @click="submit"
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

.field__label {
  font-size: 0.9rem;
  font-weight: 600;
}

:deep(.p-selectbutton) {
  flex-wrap: wrap;
}
</style>
