<script setup lang="ts">
import type {
  VerificationDecisionRequest,
  VerificationRequest,
  VerificationStatus,
} from '~/entities/verification'
import { formatDateTime } from '~/shared/lib'
import { EmptyState } from '~/shared/ui'

withDefaults(
  defineProps<{ requests: VerificationRequest[]; loading?: boolean; pending?: boolean; timeZone?: string }>(),
  { loading: false, pending: false, timeZone: undefined },
)

const emit = defineEmits<{
  decide: [item: VerificationRequest, payload: VerificationDecisionRequest]
}>()

const severity: Record<VerificationStatus, 'success' | 'warn' | 'danger'> = {
  pending: 'warn',
  approved: 'success',
  rejected: 'danger',
}

const labels: Record<VerificationStatus, string> = {
  pending: 'На проверке',
  approved: 'Одобрена',
  rejected: 'Отклонена',
}

const severityOf = (status: VerificationStatus) => severity[status]
const labelOf = (status: VerificationStatus) => labels[status]

const documentLabels: Record<string, string> = {
  verification_passport: 'Паспорт',
  verification_registration: 'Регистрация',
  verification_selfie: 'Селфи',
}

const target = ref<VerificationRequest | null>(null)
const decision = ref<VerificationDecisionRequest['decision']>('approved')
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
  decision.value === 'approved' || comment.value.trim().length >= 3,
)

const open = (item: VerificationRequest, next: VerificationDecisionRequest['decision']) => {
  decision.value = next
  comment.value = ''
  target.value = item
}

const submit = () => {
  const item = target.value

  if (!item || !canSubmit.value) {
    return
  }

  emit('decide', item, {
    decision: decision.value,
    comment: comment.value.trim() || undefined,
    version: item.version,
  })
  target.value = null
}
</script>

<template>
  <DataTable
    :value="requests"
    data-key="id"
    :loading="loading"
    striped-rows
    size="small"
    scrollable
    class="admin-table"
  >
    <template #empty>
      <EmptyState
        title="Заявок нет"
        description="В выбранном фильтре нет заявок на верификацию"
      />
    </template>

    <Column
      header="Заявитель"
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
      header="Паспорт"
      style="min-width: 180px"
    >
      <template #body="{ data }">
        <div class="cell">
          <span>{{ data.passport.passport_number }}</span>
          <span class="muted">{{ data.passport.birth_date }}</span>
        </div>
      </template>
    </Column>

    <Column
      header="Документы"
      style="min-width: 160px"
    >
      <template #body="{ data }">
        <div class="row cell-links">
          <a
            v-for="document in data.documents"
            :key="document.purpose"
            :href="document.url"
            target="_blank"
            rel="noopener noreferrer"
          >
            {{ documentLabels[document.purpose] ?? document.purpose }}
          </a>
        </div>
      </template>
    </Column>

    <Column
      header="Подана"
      style="min-width: 120px"
    >
      <template #body="{ data }">
        {{ formatDateTime(data.created_at, timeZone) }}
      </template>
    </Column>

    <Column
      header="Статус"
      style="min-width: 120px"
    >
      <template #body="{ data }">
        <Tag
          :severity="severityOf(data.status)"
          :value="labelOf(data.status)"
        />
      </template>
    </Column>

    <Column
      header="Комментарий"
      style="min-width: 160px; max-width: 240px"
    >
      <template #body="{ data }">
        <span
          class="clamp"
          :title="data.admin_comment ?? ''"
        >
          {{ data.admin_comment ?? '—' }}
        </span>
      </template>
    </Column>

    <Column
      header="Действия"
      style="min-width: 160px"
    >
      <template #body="{ data }">
        <div
          v-if="data.status === 'pending'"
          class="row actions"
        >
          <Button
            label="Одобрить"
            size="small"
            :disabled="pending"
            @click="open(data, 'approved')"
          />
          <Button
            label="Отклонить"
            size="small"
            severity="danger"
            text
            :disabled="pending"
            @click="open(data, 'rejected')"
          />
        </div>
        <span
          v-else
          class="muted"
        >—</span>
      </template>
    </Column>
  </DataTable>

  <Dialog
    v-model:visible="visible"
    modal
    :header="decision === 'approved' ? 'Одобрить верификацию' : 'Отклонить верификацию'"
    :style="{ width: '440px', maxWidth: '92vw' }"
  >
    <div
      v-if="target"
      class="stack"
    >
      <p style="margin: 0">
        {{ target.user.name }} · {{ target.passport.passport_number }}
      </p>
      <div class="field">
        <label for="decision-comment">
          Комментарий{{ decision === 'rejected' ? '' : ' (необязательно)' }}
        </label>
        <Textarea
          id="decision-comment"
          v-model="comment"
          rows="3"
          auto-resize
          fluid
        />
        <small
          v-if="decision === 'rejected'"
          class="muted"
        >
          Для отказа комментарий обязателен (минимум 3 символа)
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
        :label="decision === 'approved' ? 'Одобрить' : 'Отклонить'"
        :severity="decision === 'approved' ? undefined : 'danger'"
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
  min-width: 1040px;
}

.cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.cell-links {
  gap: 8px;
  font-size: 0.85rem;
}

.clamp {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.actions {
  gap: 4px;
  flex-wrap: nowrap;
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
