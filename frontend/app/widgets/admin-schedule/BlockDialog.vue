<script setup lang="ts">
import type { ScheduleBlockInterval } from '~/entities/schedule'
import type { BlockRange } from '~/features/admin-schedule'
import { dayKeyOf } from '~/shared/lib'

const props = withDefaults(
  defineProps<{
    block?: ScheduleBlockInterval | null
    range?: BlockRange | null
    lotName?: string
    pending?: boolean
    timeZone?: string
  }>(),
  { block: null, range: null, lotName: '', pending: false, timeZone: undefined },
)

const emit = defineEmits<{
  create: [reason: string]
  delete: [block: ScheduleBlockInterval]
}>()

const visible = defineModel<boolean>('visible', { required: true })
const reason = ref('')

const dayFormatter = new Intl.DateTimeFormat('ru-RU', {
  day: 'numeric',
  month: 'long',
  year: 'numeric',
  timeZone: 'UTC',
})

const dayLabel = (day: string): string => dayFormatter.format(new Date(`${day}T00:00:00.000Z`))

const blockDays = computed(() => {
  if (!props.block) {
    return null
  }

  return {
    from: dayKeyOf(new Date(props.block.start_time), props.timeZone),
    to: dayKeyOf(new Date(Date.parse(props.block.end_time) - 1), props.timeZone),
  }
})

const periodLabel = computed(() => {
  if (blockDays.value) {
    return `${dayLabel(blockDays.value.from)} — ${dayLabel(blockDays.value.to)}`
  }

  if (props.range) {
    return `${dayLabel(props.range.fromDay)} — ${dayLabel(props.range.toDay)}`
  }

  return ''
})

const title = computed(() => (props.block ? 'Блокировка лота' : 'Заблокировать дни'))
const canSubmit = computed(() => reason.value.trim().length >= 3 && reason.value.trim().length <= 200)

watch(visible, (open) => {
  if (open) {
    reason.value = ''
  }
})

const submit = () => {
  if (!canSubmit.value || props.block) {
    return
  }

  emit('create', reason.value.trim())
}

const remove = () => {
  if (props.block) {
    emit('delete', props.block)
  }
}
</script>

<template>
  <Dialog
    v-model:visible="visible"
    modal
    :header="title"
    :style="{ width: '460px', maxWidth: '94vw' }"
  >
    <div class="stack">
      <p
        v-if="lotName"
        class="dialog__lot"
      >
        {{ lotName }}
      </p>

      <p class="muted dialog__period">
        {{ periodLabel }}
      </p>

      <div
        v-if="block"
        class="stack"
      >
        <span class="field__label">Причина</span>
        <p class="dialog__reason">
          {{ block.reason }}
        </p>
      </div>

      <div
        v-else
        class="field"
      >
        <label for="block-reason">Причина</label>
        <InputText
          id="block-reason"
          v-model="reason"
          maxlength="200"
          placeholder="Например, техобслуживание"
          fluid
        />
        <small class="muted">От 3 до 200 символов. Дни блокируются целиком.</small>
      </div>
    </div>

    <template #footer>
      <Button
        label="Закрыть"
        text
        @click="visible = false"
      />
      <Button
        v-if="block"
        label="Удалить блокировку"
        severity="danger"
        :loading="pending"
        @click="remove"
      />
      <Button
        v-else
        label="Заблокировать"
        :disabled="!canSubmit"
        :loading="pending"
        @click="submit"
      />
    </template>
  </Dialog>
</template>

<style scoped>
.dialog__lot {
  margin: 0;
  font-size: 1.05rem;
  font-weight: 700;
}

.dialog__period {
  margin: 0;
}

.dialog__reason {
  margin: 0;
  padding: 10px 12px;
  border: 1px solid var(--p-content-border-color);
  border-radius: var(--p-content-border-radius);
  background: var(--p-content-background);
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
</style>
