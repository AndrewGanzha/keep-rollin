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
  <div
    v-if="loading"
    class="stack"
  >
    <Skeleton
      v-for="index in 2"
      :key="index"
      height="220px"
      border-radius="16px"
    />
  </div>

  <EmptyState
    v-else-if="requests.length === 0"
    title="Заявок нет"
    description="В выбранном фильтре нет заявок на верификацию"
  />

  <div
    v-else
    class="stack"
  >
    <Card
      v-for="item in requests"
      :key="item.id"
    >
      <template #title>
        <div class="row request__title">
          <span>{{ item.user.name }}</span>
          <Tag
            :severity="severity[item.status]"
            :value="labels[item.status]"
          />
        </div>
      </template>

      <template #content>
        <div class="request__grid">
          <dl class="request__passport">
            <dt>Email</dt>
            <dd>{{ item.user.email }}</dd>
            <dt>ФИО</dt>
            <dd>{{ item.passport.full_name }}</dd>
            <dt>Дата рождения</dt>
            <dd>{{ item.passport.birth_date }}</dd>
            <dt>Паспорт</dt>
            <dd>{{ item.passport.passport_number }}</dd>
            <dt>Выдан</dt>
            <dd>{{ item.passport.issued_by }}</dd>
          </dl>

          <div
            class="stack"
            style="gap: 6px"
          >
            <span class="muted">Документы</span>
            <div class="row">
              <a
                v-for="document in item.documents"
                :key="document.purpose"
                :href="document.url"
                target="_blank"
                rel="noopener noreferrer"
              >
                {{ documentLabels[document.purpose] ?? document.purpose }}
              </a>
            </div>
            <span class="muted">Подана: {{ formatDateTime(item.created_at, timeZone) }}</span>
            <span
              v-if="item.reviewed_at"
              class="muted"
            >
              Решение: {{ formatDateTime(item.reviewed_at, timeZone) }}
            </span>
            <span
              v-if="item.admin_comment"
              class="muted"
            >
              Комментарий: {{ item.admin_comment }}
            </span>
          </div>
        </div>
      </template>

      <template
        v-if="item.status === 'pending'"
        #footer
      >
        <div class="row">
          <Button
            label="Одобрить"
            size="small"
            :disabled="pending"
            @click="open(item, 'approved')"
          />
          <Button
            label="Отклонить"
            size="small"
            severity="danger"
            text
            :disabled="pending"
            @click="open(item, 'rejected')"
          />
        </div>
      </template>
    </Card>
  </div>

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
      <div class="stack request__field">
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
.request__title {
  justify-content: space-between;
}

.request__grid {
  display: grid;
  gap: 16px;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
}

.request__passport {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 6px 12px;
  margin: 0;
}

.request__passport dt {
  color: var(--p-text-muted-color);
}

.request__passport dd {
  margin: 0;
  font-weight: 600;
}

.request__field {
  gap: 6px;
}

.request__field label {
  font-size: 0.9rem;
  font-weight: 600;
}
</style>
