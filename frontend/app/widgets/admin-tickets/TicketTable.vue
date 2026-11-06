<script setup lang="ts">
import type { Ticket, TicketCategory, TicketPatchRequest, TicketStatus } from '~/entities/ticket'
import { formatDateTime } from '~/shared/lib'
import { EmptyState } from '~/shared/ui'

withDefaults(
  defineProps<{ tickets: Ticket[]; loading?: boolean; pending?: boolean; timeZone?: string }>(),
  { loading: false, pending: false, timeZone: undefined },
)

const emit = defineEmits<{
  apply: [ticket: Ticket, payload: TicketPatchRequest]
}>()

const severity: Record<TicketStatus, 'warn' | 'info' | 'success'> = {
  submitted: 'warn',
  in_progress: 'info',
  resolved: 'success',
}

const statusLabels: Record<TicketStatus, string> = {
  submitted: 'Новый',
  in_progress: 'В работе',
  resolved: 'Решён',
}

const categoryLabels: Record<TicketCategory, string> = {
  no_power: 'Не включается',
  no_drive: 'Не едет',
  battery: 'Аккумулятор',
  damage: 'Повреждение',
  other: 'Другое',
}

const categoryLabel = (category: TicketCategory) => categoryLabels[category]
const severityOf = (status: TicketStatus) => severity[status]
const statusLabel = (status: TicketStatus) => statusLabels[status]

const expanded = ref<Record<string, boolean>>({})

const target = ref<Ticket | null>(null)
const nextStatus = ref<TicketPatchRequest['status']>('in_progress')
const comment = ref('')
const visible = computed({
  get: () => target.value !== null,
  set: (value: boolean) => {
    if (!value) {
      target.value = null
    }
  },
})
const canSubmit = computed(() =>
  nextStatus.value === 'in_progress' || comment.value.trim().length >= 3,
)

const open = (ticket: Ticket, status: TicketPatchRequest['status']) => {
  nextStatus.value = status
  comment.value = ticket.admin_comment ?? ''
  target.value = ticket
}

const submit = () => {
  const ticket = target.value

  if (!ticket || !canSubmit.value) {
    return
  }

  emit('apply', ticket, {
    status: nextStatus.value,
    admin_comment: comment.value.trim() || undefined,
    version: ticket.version,
  })
  target.value = null
}
</script>

<template>
  <DataTable
    v-model:expanded-rows="expanded"
    :value="tickets"
    data-key="id"
    :loading="loading"
    striped-rows
    size="small"
    scrollable
    class="admin-table"
  >
    <template #empty>
      <EmptyState
        title="Тикетов нет"
        description="В выбранном фильтре нет обращений"
      />
    </template>

    <Column
      expander
      style="width: 3rem"
    />

    <Column
      header="Лот"
      style="min-width: 140px"
    >
      <template #body="{ data }">
        {{ data.lot.name }}
      </template>
    </Column>

    <Column
      header="Категория"
      style="min-width: 130px"
    >
      <template #body="{ data }">
        {{ categoryLabel(data.category) }}
      </template>
    </Column>

    <Column
      header="Арендатор"
      style="min-width: 180px"
    >
      <template #body="{ data }">
        <div class="cell">
          <span>{{ data.user.name }}</span>
          <span class="muted">{{ data.user.email }}</span>
        </div>
      </template>
    </Column>

    <Column
      header="Статус"
      style="min-width: 110px"
    >
      <template #body="{ data }">
        <Tag
          :severity="severityOf(data.status)"
          :value="statusLabel(data.status)"
        />
      </template>
    </Column>

    <Column
      header="Создан"
      style="min-width: 120px"
    >
      <template #body="{ data }">
        {{ formatDateTime(data.created_at, timeZone) }}
      </template>
    </Column>

    <Column
      header="Действия"
      style="min-width: 130px"
    >
      <template #body="{ data }">
        <div class="row actions">
          <Button
            v-if="data.status === 'submitted'"
            label="В работу"
            size="small"
            :disabled="pending"
            @click="open(data, 'in_progress')"
          />
          <Button
            v-else-if="data.status === 'in_progress'"
            label="Решить"
            size="small"
            :disabled="pending"
            @click="open(data, 'resolved')"
          />
          <span
            v-else
            class="muted"
          >—</span>
        </div>
      </template>
    </Column>

    <template #expansion="{ data }">
      <div class="stack ticket-detail">
        <p style="margin: 0">
          {{ data.description }}
        </p>
        <div
          v-if="data.photo_urls.length > 0"
          class="row"
        >
          <a
            v-for="url in data.photo_urls"
            :key="url"
            :href="url"
            target="_blank"
            rel="noopener noreferrer"
          >
            Фото
          </a>
        </div>
        <span
          v-if="data.admin_comment"
          class="muted"
        >
          Комментарий: {{ data.admin_comment }}
        </span>
        <span
          v-if="data.resolved_at"
          class="muted"
        >
          Решён: {{ formatDateTime(data.resolved_at, timeZone) }}
        </span>
      </div>
    </template>
  </DataTable>

  <Dialog
    v-model:visible="visible"
    modal
    :header="nextStatus === 'resolved' ? 'Решить тикет' : 'Взять в работу'"
    :style="{ width: '440px', maxWidth: '92vw' }"
  >
    <div
      v-if="target"
      class="stack"
    >
      <p style="margin: 0">
        {{ target.lot.name }} · {{ categoryLabel(target.category) }}
      </p>
      <div class="field">
        <label for="ticket-comment">
          Комментарий{{ nextStatus === 'resolved' ? '' : ' (необязательно)' }}
        </label>
        <Textarea
          id="ticket-comment"
          v-model="comment"
          rows="3"
          auto-resize
          fluid
        />
        <small
          v-if="nextStatus === 'resolved'"
          class="muted"
        >
          Для решения комментарий обязателен (минимум 3 символа)
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
        :label="nextStatus === 'resolved' ? 'Решить' : 'В работу'"
        :disabled="!canSubmit"
        :loading="pending"
        @click="submit"
      />
    </template>
  </Dialog>
</template>

<style scoped>
.admin-table :deep(.p-tag) {
  white-space: nowrap;
}

.admin-table :deep(.p-datatable-table) {
  min-width: 900px;
}

.cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.actions {
  gap: 4px;
  flex-wrap: nowrap;
}

.ticket-detail {
  gap: 8px;
  padding: 8px 4px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.field label {
  font-size: 0.9rem;
  font-weight: 600;
}
</style>
