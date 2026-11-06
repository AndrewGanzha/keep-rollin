<script setup lang="ts">
import {
  rentalStatusLabels,
  rentalStatusSeverity,
  type AdminRental,
  type CancelAdminRentalRequest,
  type CloseRentalRequest,
} from '~/entities/rental'
import { formatDateTime, formatDuration, formatMoney } from '~/shared/lib'

const props = withDefaults(
  defineProps<{ rental: AdminRental | null; pending?: boolean; timeZone?: string }>(),
  { pending: false, timeZone: undefined },
)

const emit = defineEmits<{
  'update:rental': [rental: AdminRental | null]
  close: [rental: AdminRental, payload: CloseRentalRequest]
  cancel: [rental: AdminRental, payload: CancelAdminRentalRequest]
}>()

type Mode = 'view' | 'close' | 'cancel'

const mode = ref<Mode>('view')
const comment = ref('')
const lotStatus = ref<CloseRentalRequest['lot_status']>('active')
const reason = ref('')

const visible = computed({
  get: () => props.rental !== null,
  set: (value: boolean) => {
    if (!value) {
      emit('update:rental', null)
    }
  },
})

watch(() => props.rental?.id, () => {
  mode.value = 'view'
  comment.value = ''
  lotStatus.value = 'active'
  reason.value = ''
})

const canClose = computed(() => comment.value.trim().length >= 3)
const canCancel = computed(() => reason.value.trim().length >= 3)

const submitClose = () => {
  if (!props.rental || !canClose.value) {
    return
  }

  emit('close', props.rental, { comment: comment.value.trim(), lot_status: lotStatus.value })
}

const submitCancel = () => {
  if (!props.rental || !canCancel.value) {
    return
  }

  emit('cancel', props.rental, { reason: reason.value.trim() })
}
</script>

<template>
  <Dialog
    v-model:visible="visible"
    modal
    :style="{ width: '480px', maxWidth: '94vw' }"
  >
    <template #header>
      <div
        v-if="rental"
        class="row details__header"
      >
        <span>{{ rental.lot.name }}</span>
        <Tag
          :severity="rentalStatusSeverity[rental.status]"
          :value="rentalStatusLabels[rental.status]"
        />
      </div>
    </template>

    <div
      v-if="rental"
      class="stack"
    >
      <template v-if="mode === 'view'">
        <dl class="details__list">
          <dt>Арендатор</dt>
          <dd>{{ rental.user.name }} · {{ rental.user.email }}</dd>
          <dt>Интервал</dt>
          <dd>{{ formatDateTime(rental.start_time, timeZone) }} — {{ formatDateTime(rental.end_time, timeZone) }}</dd>
          <dt>Стоимость</dt>
          <dd>{{ formatMoney(rental.price_minor, rental.currency) }}</dd>
          <dt v-if="rental.remaining_seconds > 0">
            Осталось
          </dt>
          <dd v-if="rental.remaining_seconds > 0">
            {{ formatDuration(rental.remaining_seconds) }}
          </dd>
          <dt>Версия</dt>
          <dd>{{ rental.version }}</dd>
        </dl>

        <NuxtLink :to="`/lots/${rental.lot.slug}`">
          Карточка лота
        </NuxtLink>
      </template>

      <template v-else-if="mode === 'close'">
        <Message
          v-if="rental.status === 'overdue'"
          severity="warn"
          size="small"
          :closable="false"
        >
          Аренда просрочена. Закрытие освободит слот и вернёт лот в парк.
        </Message>

        <div class="details__field">
          <label for="details-lot-status">Статус лота после закрытия</label>
          <Select
            id="details-lot-status"
            v-model="lotStatus"
            :options="[
              { label: 'В работе', value: 'active' },
              { label: 'Обслуживание', value: 'maintenance' },
            ]"
            option-label="label"
            option-value="value"
            fluid
          />
        </div>

        <div class="details__field">
          <label for="details-close-comment">Комментарий</label>
          <Textarea
            id="details-close-comment"
            v-model="comment"
            rows="3"
            auto-resize
            fluid
          />
          <small class="muted">Минимум 3 символа</small>
        </div>
      </template>

      <template v-else>
        <div class="details__field">
          <label for="details-cancel-reason">Причина отмены</label>
          <Textarea
            id="details-cancel-reason"
            v-model="reason"
            rows="3"
            auto-resize
            fluid
          />
          <small class="muted">Минимум 3 символа</small>
        </div>
      </template>
    </div>

    <template #footer>
      <template v-if="rental">
        <template v-if="mode === 'view'">
          <Button
            v-if="['booked', 'active'].includes(rental.status)"
            label="Отменить"
            severity="danger"
            text
            :disabled="pending"
            @click="mode = 'cancel'"
          />
          <Button
            v-if="['booked', 'active', 'overdue'].includes(rental.status)"
            label="Закрыть аренду"
            :disabled="pending"
            @click="mode = 'close'"
          />
        </template>

        <template v-else-if="mode === 'close'">
          <Button
            label="Назад"
            text
            @click="mode = 'view'"
          />
          <Button
            label="Закрыть"
            :disabled="!canClose"
            :loading="pending"
            @click="submitClose"
          />
        </template>

        <template v-else>
          <Button
            label="Назад"
            text
            @click="mode = 'view'"
          />
          <Button
            label="Отменить аренду"
            severity="danger"
            :disabled="!canCancel"
            :loading="pending"
            @click="submitCancel"
          />
        </template>
      </template>
    </template>
  </Dialog>
</template>

<style scoped>
.details__header {
  justify-content: space-between;
  font-weight: 700;
}

.details__list {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 6px 16px;
  margin: 0;
}

.details__list dt {
  color: var(--p-text-muted-color);
}

.details__list dd {
  margin: 0;
  font-weight: 600;
}

.details__field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.details__field label {
  font-size: 0.9rem;
  font-weight: 600;
}
</style>
