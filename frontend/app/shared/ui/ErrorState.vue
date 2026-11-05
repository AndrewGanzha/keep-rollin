<script setup lang="ts">
import { ApiError } from '~/shared/api'

const props = defineProps<{ error: unknown }>()
const emit = defineEmits<{ retry: [] }>()

const message = computed(() => {
  if (props.error instanceof ApiError) {
    return props.error.status === 0
      ? 'Сервис недоступен. Проверьте, запущен ли мок-сервер.'
      : props.error.message
  }

  return 'Не удалось загрузить данные'
})
</script>

<template>
  <Message
    severity="error"
    :closable="false"
  >
    <div
      class="row"
      style="justify-content: space-between"
    >
      <span>{{ message }}</span>
      <Button
        label="Повторить"
        size="small"
        text
        @click="emit('retry')"
      />
    </div>
  </Message>
</template>
