<script setup lang="ts">
import type {
  AdminVerificationRequestSummary,
  VerificationDecisionRequest,
  VerificationRequest,
  VerificationStatus,
} from '~/entities/verification'
import { formatDateTime } from '~/shared/lib'
import { EmptyState, ErrorState } from '~/shared/ui'

const props = withDefaults(
  defineProps<{
    requests: AdminVerificationRequestSummary[]
    loading?: boolean
    pending?: boolean
    timeZone?: string
    detail: VerificationRequest | null
    detailError: unknown
    detailPending: boolean
  }>(),
  { loading: false, pending: false, timeZone: undefined },
)

const emit = defineEmits<{
  decide: [item: AdminVerificationRequestSummary, payload: VerificationDecisionRequest]
  'load-detail': [id: string]
  'clear-detail': []
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

const documentLabels: Record<VerificationRequest['documents'][number]['purpose'], string> = {
  verification_passport: 'Паспорт',
  verification_registration: 'Регистрация',
  verification_selfie: 'Селфи',
}

type Decision = VerificationDecisionRequest['decision']

const decisionLabels: Record<Decision, string> = {
  approved: 'Одобрить',
  rejected: 'Отклонить',
}

const target = ref<AdminVerificationRequestSummary | null>(null)
const decision = ref<Decision>()
const comment = ref('')

const close = () => {
  target.value = null
  decision.value = undefined
  comment.value = ''
  emit('clear-detail')
}

const visible = computed({
  get: () => target.value !== null,
  set: (value: boolean) => {
    if (!value) {
      close()
    }
  },
})
const currentDetail = computed(() => props.detail?.id === target.value?.id ? props.detail : null)
const canSubmit = computed(() =>
  decision.value === 'approved' || comment.value.trim().length > 0,
)
const canDecide = computed(() => currentDetail.value?.status === 'pending')

const open = (item: AdminVerificationRequestSummary, next?: Decision) => {
  decision.value = next
  comment.value = ''
  target.value = item
  emit('load-detail', item.id)
}

const submit = () => {
  const item = target.value
  const detail = currentDetail.value
  const next = decision.value

  if (!item || detail?.status !== 'pending' || !next || !canSubmit.value || props.pending) {
    return
  }

  emit('decide', item, {
    decision: next,
    comment: comment.value.trim() || undefined,
    version: detail.version,
  })
  close()
}

onBeforeUnmount(close)
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
        <div class="row actions">
          <Button
            label="Подробнее"
            size="small"
            text
            @click="open(data)"
          />
          <Button
            v-if="data.status === 'pending'"
            label="Одобрить"
            size="small"
            :disabled="pending"
            @click="open(data, 'approved')"
          />
          <Button
            v-if="data.status === 'pending'"
            label="Отклонить"
            size="small"
            severity="danger"
            text
            :disabled="pending"
            @click="open(data, 'rejected')"
          />
        </div>
      </template>
    </Column>
  </DataTable>

  <Dialog
    v-model:visible="visible"
    modal
    :header="decision ? `${decisionLabels[decision]} верификацию` : 'Заявка на верификацию'"
    :style="{ width: '480px', maxWidth: '92vw' }"
  >
    <div
      v-if="target"
      class="stack"
    >
      <p style="margin: 0">
        {{ target.user.name }} · {{ target.user.email }}
      </p>
      <p
        v-if="detailPending"
        role="status"
        class="muted"
      >
        Загружаем паспортные данные и документы…
      </p>
      <ErrorState
        v-else-if="detailError"
        :error="detailError"
        @retry="emit('load-detail', target.id)"
      />
      <template v-else-if="currentDetail">
        <dl class="passport">
          <dt>ФИО по паспорту</dt>
          <dd>{{ currentDetail.passport.full_name }}</dd>
          <dt>Дата рождения</dt>
          <dd>{{ currentDetail.passport.birth_date }}</dd>
          <dt>Номер паспорта</dt>
          <dd>{{ currentDetail.passport.passport_number }}</dd>
          <dt>Кем выдан</dt>
          <dd>{{ currentDetail.passport.issued_by }}</dd>
        </dl>
        <div class="row document-links">
          <a
            v-for="document in currentDetail.documents"
            :key="document.purpose"
            :href="document.url"
            target="_blank"
            rel="noopener noreferrer"
          >
            {{ documentLabels[document.purpose] }}
          </a>
        </div>
      </template>
      <div
        v-if="decision && canDecide"
        class="field"
      >
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
          Для отказа комментарий обязателен
        </small>
      </div>
    </div>

    <template #footer>
      <Button
        :label="decision ? 'Отмена' : 'Закрыть'"
        text
        @click="visible = false"
      />
      <Button
        v-if="decision && canDecide"
        :label="decisionLabels[decision]"
        :severity="decision === 'approved' ? undefined : 'danger'"
        :disabled="pending || !canSubmit"
        :loading="pending"
        @click="submit"
      />
      <template v-else-if="canDecide">
        <Button
          label="Одобрить"
          :disabled="pending"
          @click="decision = 'approved'"
        />
        <Button
          label="Отклонить"
          severity="danger"
          text
          :disabled="pending"
          @click="decision = 'rejected'"
        />
      </template>
    </template>
  </Dialog>
</template>

<style scoped>
.admin-table :deep(.p-tag) {
  white-space: nowrap;
}

.admin-table :deep(.p-datatable-table) {
  min-width: 860px;
}

.cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.document-links {
  gap: 8px;
  flex-wrap: wrap;
}

.passport {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 4px 12px;
  margin: 0;
}

.passport dd {
  margin: 0;
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
