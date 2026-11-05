<script setup lang="ts">
import type {
  AdminRental,
  AdminRentalStatus,
  CancelAdminRentalRequest,
  CloseRentalRequest,
} from '~/entities/rental'
import { formatDateTime, formatMoney } from '~/shared/lib'
import { EmptyState } from '~/shared/ui'

withDefaults(
  defineProps<{ rentals: AdminRental[]; loading?: boolean; pending?: boolean; timeZone?: string }>(),
  { loading: false, pending: false, timeZone: undefined },
)

const emit = defineEmits<{
  close: [rental: AdminRental, payload: CloseRentalRequest]
  cancel: [rental: AdminRental, payload: CancelAdminRentalRequest]
}>()

const severity: Record<AdminRentalStatus, 'success' | 'info' | 'warn' | 'danger' | 'secondary'> = {
  booked: 'info',
  active: 'success',
  overdue: 'danger',
  completed: 'secondary',
  cancelled: 'secondary',
}

const labels: Record<AdminRentalStatus, string> = {
  booked: 'Забронировано',
  active: 'Активна',
  overdue: 'Просрочена',
  completed: 'Завершена',
  cancelled: 'Отменена',
}

const closeTarget = ref<AdminRental | null>(null)
const closeComment = ref('')
const closeLotStatus = ref<CloseRentalRequest['lot_status']>('active')
const closeVisible = computed({
  get: () => closeTarget.value !== null,
  set: (value: boolean) => {
    if (!value) {
      closeTarget.value = null
    }
  },
})
const canSubmitClose = computed(() => closeComment.value.trim().length >= 3)

const openClose = (rental: AdminRental) => {
  closeComment.value = ''
  closeLotStatus.value = 'active'
  closeTarget.value = rental
}

const submitClose = () => {
  const rental = closeTarget.value

  if (!rental || !canSubmitClose.value) {
    return
  }

  emit('close', rental, { comment: closeComment.value.trim(), lot_status: closeLotStatus.value })
  closeTarget.value = null
}

const cancelTarget = ref<AdminRental | null>(null)
const cancelReason = ref('')
const cancelVisible = computed({
  get: () => cancelTarget.value !== null,
  set: (value: boolean) => {
    if (!value) {
      cancelTarget.value = null
    }
  },
})
const canSubmitCancel = computed(() => cancelReason.value.trim().length >= 3)

const openCancel = (rental: AdminRental) => {
  cancelReason.value = ''
  cancelTarget.value = rental
}

const submitCancel = () => {
  const rental = cancelTarget.value

  if (!rental || !canSubmitCancel.value) {
    return
  }

  emit('cancel', rental, { reason: cancelReason.value.trim() })
  cancelTarget.value = null
}
</script>

<template>
  <div
    v-if="loading"
    class="stack"
  >
    <Skeleton
      v-for="index in 3"
      :key="index"
      height="170px"
      border-radius="16px"
    />
  </div>

  <EmptyState
    v-else-if="rentals.length === 0"
    title="Аренд нет"
    description="В выбранном фильтре нет аренд"
  />

  <div
    v-else
    class="stack"
  >
    <Card
      v-for="rental in rentals"
      :key="rental.id"
    >
      <template #title>
        <div class="row rental__title">
          <span>{{ rental.lot.name }}</span>
          <Tag
            :severity="severity[rental.status]"
            :value="labels[rental.status]"
          />
        </div>
      </template>

      <template #content>
        <div class="rental__grid">
          <div class="stack rental__cell">
            <span class="muted">Арендатор</span>
            <span>{{ rental.user.name }}</span>
            <span class="muted">{{ rental.user.email }}</span>
          </div>
          <div class="stack rental__cell">
            <span class="muted">Интервал</span>
            <span>{{ formatDateTime(rental.start_time, timeZone) }} — {{ formatDateTime(rental.end_time, timeZone) }}</span>
            <span class="muted">Версия: {{ rental.version }}</span>
          </div>
          <div class="stack rental__cell">
            <span class="muted">Стоимость</span>
            <span>{{ formatMoney(rental.price_minor, rental.currency) }}</span>
            <NuxtLink :to="`/lots/${rental.lot.slug}`">
              Карточка лота
            </NuxtLink>
          </div>
        </div>
      </template>

      <template #footer>
        <div class="row">
          <Button
            v-if="['booked', 'active', 'overdue'].includes(rental.status)"
            label="Закрыть аренду"
            size="small"
            :disabled="pending"
            @click="openClose(rental)"
          />
          <Button
            v-if="['booked', 'active'].includes(rental.status)"
            label="Отменить"
            size="small"
            severity="danger"
            text
            :disabled="pending"
            @click="openCancel(rental)"
          />
        </div>
      </template>
    </Card>
  </div>

  <Dialog
    v-model:visible="closeVisible"
    modal
    header="Закрыть аренду"
    :style="{ width: '440px', maxWidth: '92vw' }"
  >
    <div
      v-if="closeTarget"
      class="stack"
    >
      <p style="margin: 0">
        {{ closeTarget.lot.name }} · {{ closeTarget.user.name }}
      </p>
      <Message
        v-if="closeTarget.status === 'overdue'"
        severity="warn"
        size="small"
        :closable="false"
      >
        Аренда просрочена. Закрытие освободит слот и вернёт лот в парк.
      </Message>

      <div class="stack close-form__field">
        <label for="close-lot-status">Статус лота после закрытия</label>
        <Select
          id="close-lot-status"
          v-model="closeLotStatus"
          :options="[
            { label: 'В работе', value: 'active' },
            { label: 'Обслуживание', value: 'maintenance' },
          ]"
          option-label="label"
          option-value="value"
          fluid
        />
      </div>

      <div class="stack close-form__field">
        <label for="close-comment">Комментарий</label>
        <Textarea
          id="close-comment"
          v-model="closeComment"
          rows="3"
          auto-resize
          fluid
        />
        <small class="muted">Минимум 3 символа</small>
      </div>
    </div>

    <template #footer>
      <Button
        label="Отмена"
        text
        @click="closeVisible = false"
      />
      <Button
        label="Закрыть"
        :disabled="!canSubmitClose"
        :loading="pending"
        @click="submitClose"
      />
    </template>
  </Dialog>

  <Dialog
    v-model:visible="cancelVisible"
    modal
    header="Отменить аренду"
    :style="{ width: '440px', maxWidth: '92vw' }"
  >
    <div
      v-if="cancelTarget"
      class="stack"
    >
      <p style="margin: 0">
        {{ cancelTarget.lot.name }} · {{ cancelTarget.user.name }}
      </p>
      <div class="stack close-form__field">
        <label for="cancel-reason">Причина отмены</label>
        <Textarea
          id="cancel-reason"
          v-model="cancelReason"
          rows="3"
          auto-resize
          fluid
        />
        <small class="muted">Минимум 3 символа</small>
      </div>
    </div>

    <template #footer>
      <Button
        label="Не отменять"
        text
        @click="cancelVisible = false"
      />
      <Button
        label="Отменить аренду"
        severity="danger"
        :disabled="!canSubmitCancel"
        :loading="pending"
        @click="submitCancel"
      />
    </template>
  </Dialog>
</template>

<style scoped>
.rental__title {
  justify-content: space-between;
}

.rental__grid {
  display: grid;
  gap: 16px;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
}

.rental__cell {
  gap: 4px;
}

.close-form__field {
  gap: 6px;
}

.close-form__field label {
  font-size: 0.9rem;
  font-weight: 600;
}
</style>
