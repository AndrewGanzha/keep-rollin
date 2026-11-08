<script setup lang="ts">
import type { AnalyticsLotDetail, AnalyticsRental } from '~/entities/analytics'
import { RevenueBars } from '~/entities/analytics'
import {
  rentalStatusLabels,
  rentalStatusSeverity,
} from '~/entities/rental'
import { useTenant } from '~/entities/tenant'
import { formatDateTime, formatMoney } from '~/shared/lib'
import { EmptyState } from '~/shared/ui'

const props = defineProps<{ detail: AnalyticsLotDetail | null }>()
const emit = defineEmits<{ close: [] }>()

const tenant = useTenant()
const timeZone = computed(() => tenant.value?.timezone)

const visible = computed({
  get: () => props.detail !== null,
  set: (value: boolean) => {
    if (!value) {
      emit('close')
    }
  },
})

const summary = computed(() => props.detail?.summary ?? null)

const rentalStatus = (rental: AnalyticsRental) => rentalStatusSeverity[rental.status]
const rentalStatusLabel = (rental: AnalyticsRental) => rentalStatusLabels[rental.status]
</script>

<template>
  <Dialog
    v-model:visible="visible"
    modal
    :header="detail ? `Лот: ${detail.lot.name}` : 'Лот'"
    :style="{ width: '780px', maxWidth: '96vw' }"
  >
    <div
      v-if="detail && summary"
      class="stack"
    >
      <div class="kpis">
        <div class="kpi">
          <span class="muted">Выручка</span>
          <strong>{{ formatMoney(summary.revenue_minor) }}</strong>
        </div>
        <div class="kpi">
          <span class="muted">Аренд</span>
          <strong>{{ summary.rentals_count }}</strong>
        </div>
        <div class="kpi">
          <span class="muted">Средний чек</span>
          <strong>{{ formatMoney(summary.avg_rental_minor) }}</strong>
        </div>
        <div class="kpi">
          <span class="muted">Загрузка</span>
          <strong>{{ summary.utilization_pct }}%</strong>
        </div>
      </div>

      <div>
        <h3 class="section-title detail__title">
          Выручка по дням
        </h3>
        <RevenueBars :buckets="detail.daily" />
      </div>

      <div>
        <h3 class="section-title detail__title">
          Аренды за период
        </h3>
        <DataTable
          :value="detail.rentals"
          data-key="id"
          striped-rows
          size="small"
          scrollable
          class="admin-table"
        >
          <template #empty>
            <EmptyState
              title="Аренд нет"
              description="За выбранный период аренд не было"
            />
          </template>
          <Column
            header="Интервал"
            style="min-width: 160px"
          >
            <template #body="{ data }">
              {{ formatDateTime(data.start_time, timeZone) }} — {{ formatDateTime(data.end_time, timeZone) }}
            </template>
          </Column>
          <Column
            header="Арендатор"
            style="min-width: 150px"
          >
            <template #body="{ data }">
              {{ data.user.name }}
            </template>
          </Column>
          <Column
            header="Статус"
            style="min-width: 110px"
          >
            <template #body="{ data }">
              <Tag
                :severity="rentalStatus(data)"
                :value="rentalStatusLabel(data)"
              />
            </template>
          </Column>
          <Column
            header="Сумма"
            style="min-width: 100px"
          >
            <template #body="{ data }">
              {{ formatMoney(data.price_minor, data.currency) }}
            </template>
          </Column>
        </DataTable>
      </div>
    </div>

    <template #footer>
      <Button
        label="Закрыть"
        text
        @click="visible = false"
      />
    </template>
  </Dialog>
</template>

<style scoped>
.kpis {
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
}

.kpi {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px 10px;
  border: 1px solid var(--p-content-border-color);
  border-radius: var(--p-content-border-radius);
  font-size: 0.8rem;
}

.kpi strong {
  font-size: 1.05rem;
}

.detail__title {
  margin-bottom: 8px;
  font-size: 1rem;
}

.admin-table :deep(.p-datatable-table) {
  min-width: 620px;
}

.admin-table :deep(.p-tag) {
  white-space: nowrap;
}
</style>
