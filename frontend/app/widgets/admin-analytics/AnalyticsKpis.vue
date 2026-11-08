<script setup lang="ts">
import type { AnalyticsSummary } from '~/entities/analytics'
import { formatMoney } from '~/shared/lib'

const props = defineProps<{ summary: AnalyticsSummary }>()

const items = computed(() => [
  { label: 'Выручка', value: formatMoney(props.summary.revenue_minor) },
  { label: 'Аренд', value: String(props.summary.rentals_count) },
  { label: 'Средний чек', value: formatMoney(props.summary.avg_rental_minor) },
  { label: 'Загрузка', value: `${props.summary.utilization_pct}%` },
  { label: 'Отменено', value: String(props.summary.cancelled_count) },
  { label: 'Просрочено', value: String(props.summary.overdue_count) },
])
</script>

<template>
  <div class="kpis">
    <Card
      v-for="item in items"
      :key="item.label"
    >
      <template #content>
        <div class="kpi">
          <span class="muted">{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
        </div>
      </template>
    </Card>
  </div>
</template>

<style scoped>
.kpis {
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
}

.kpi {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 0.85rem;
}

.kpi strong {
  font-size: 1.25rem;
  font-weight: 700;
}
</style>
