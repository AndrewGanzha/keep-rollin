<script setup lang="ts">
import { formatRelativeChange, type AnalyticsComparison, type AnalyticsSummary } from '~/entities/analytics'
import { formatMoney } from '~/shared/lib'

const props = defineProps<{
  summary: AnalyticsSummary
  currency?: string
  comparison?: AnalyticsComparison | null
}>()

const amount = (value: number) => formatMoney(value, props.currency)
const percentage = (value: number) => `${value.toLocaleString('ru-RU')}%`
const points = (value: number) => `${value.toLocaleString('ru-RU')} п. п.`
const metrics = [
  { field: 'revenue_minor', label: 'Выручка', format: amount },
  { field: 'rentals_count', label: 'Аренд', format: String },
  { field: 'avg_rental_minor', label: 'Средний чек', format: amount },
  { field: 'utilization_pct', label: 'Загрузка', format: percentage, formatDelta: points },
  { field: 'cancelled_count', label: 'Отменено', format: String, lowerIsBetter: true },
  { field: 'overdue_count', label: 'Просрочено', format: String, lowerIsBetter: true },
] as const

const items = computed(() => metrics.map((metric) => {
  const { field, format, label } = metric
  const comparison = props.comparison
  const change = comparison?.delta[field] ?? 0
  const previous = comparison?.previous[field] ?? 0
  const favorable = 'lowerIsBetter' in metric ? change < 0 : change > 0
  const formatDelta = 'formatDelta' in metric ? metric.formatDelta : format

  return {
    label,
    value: format(props.summary[field]),
    previous: comparison ? format(previous) : null,
    delta: `${change > 0 ? '+' : ''}${formatDelta(change)}`,
    relativeDelta: formatRelativeChange(change, previous),
    deltaClass: change === 0 ? '' : favorable ? 'kpi__delta--positive' : 'kpi__delta--negative',
  }
}))
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
          <span
            v-if="item.previous !== null"
            class="muted"
          >Было {{ item.previous }} <span :class="item.deltaClass">({{ item.delta }} · {{ item.relativeDelta }})</span></span>
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

.kpi__delta--positive {
  color: var(--p-green-700);
}

.kpi__delta--negative {
  color: var(--p-red-700);
}
</style>
