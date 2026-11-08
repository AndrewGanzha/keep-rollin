<script setup lang="ts">
import type { AnalyticsBucket } from '~/entities/analytics'
import { formatMoney } from '~/shared/lib'
import { EmptyState } from '~/shared/ui'

withDefaults(defineProps<{ lots: AnalyticsBucket[]; loading?: boolean }>(), { loading: false })

const emit = defineEmits<{ select: [bucket: AnalyticsBucket] }>()

const avgCheck = (bucket: AnalyticsBucket): number => {
  const billable = bucket.rentals_count - bucket.cancelled_count

  return billable > 0 ? Math.round(bucket.revenue_minor / billable) : 0
}

const utilizationClass = (value: number): string => {
  if (value < 20) {
    return 'bar__fill bar__fill--low'
  }

  return value < 50 ? 'bar__fill bar__fill--mid' : 'bar__fill'
}
</script>

<template>
  <Card>
    <template #title>
      Доходность по лотам
    </template>

    <template #content>
      <DataTable
        :value="lots"
        data-key="key"
        :loading="loading"
        striped-rows
        size="small"
        scrollable
        class="admin-table"
      >
        <template #empty>
          <EmptyState
            title="Нет данных"
            description="За выбранный период аренд нет"
          />
        </template>

        <Column
          header="Лот"
          field="label"
          sortable
          style="min-width: 160px"
        />
        <Column
          header="Аренд"
          field="rentals_count"
          sortable
          style="min-width: 90px"
        />
        <Column
          header="Выручка"
          field="revenue_minor"
          sortable
          style="min-width: 130px"
        >
          <template #body="{ data }">
            {{ formatMoney(data.revenue_minor) }}
          </template>
        </Column>
        <Column
          header="Средний чек"
          style="min-width: 130px"
        >
          <template #body="{ data }">
            {{ formatMoney(avgCheck(data)) }}
          </template>
        </Column>
        <Column
          header="Загрузка"
          field="utilization_pct"
          sortable
          style="min-width: 160px"
        >
          <template #body="{ data }">
            <div class="util">
              <div class="bar">
                <div
                  :class="utilizationClass(data.utilization_pct)"
                  :style="{ width: `${Math.min(data.utilization_pct, 100)}%` }"
                />
              </div>
              <span>{{ data.utilization_pct }}%</span>
            </div>
          </template>
        </Column>
        <Column
          header=""
          style="width: 110px"
        >
          <template #body="{ data }">
            <Button
              label="Детали"
              size="small"
              outlined
              @click="emit('select', data)"
            />
          </template>
        </Column>
      </DataTable>
    </template>
  </Card>
</template>

<style scoped>
.admin-table :deep(.p-datatable-table) {
  min-width: 860px;
}

.util {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.8rem;
}

.bar {
  flex: 1;
  height: 8px;
  min-width: 60px;
  border-radius: 4px;
  background: var(--p-content-border-color);
  overflow: hidden;
}

.bar__fill {
  height: 100%;
  border-radius: 4px;
  background: var(--p-green-500);
}

.bar__fill--mid {
  background: var(--p-amber-500);
}

.bar__fill--low {
  background: var(--p-red-500);
}
</style>
