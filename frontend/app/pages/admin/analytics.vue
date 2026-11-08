<script setup lang="ts">
import { RevenueBars } from '~/entities/analytics'
import { periodPresets, useAdminAnalytics } from '~/features/admin-analytics'
import { ErrorState, PageHeading } from '~/shared/ui'
import {
  AnalyticsKpis,
  CategoryBreakdown,
  LotAnalyticsDialog,
  LotsAnalyticsTable,
} from '~/widgets/admin-analytics'

definePageMeta({ layout: 'admin', middleware: ['auth', 'role'] })

useHead({ title: 'Аналитика — админка' })

const {
  data,
  pending,
  error,
  refresh,
  preset,
  customRange,
  periodLabel,
  openLot,
  detail,
  closeDetail,
} = await useAdminAnalytics()
</script>

<template>
  <div class="stack">
    <PageHeading
      title="Аналитика"
      subtitle="Выручка, загрузка и доходность лотов за период"
    />

    <div class="row analytics__toolbar">
      <SelectButton
        v-model="preset"
        :options="periodPresets"
        option-label="label"
        option-value="value"
        :allow-empty="false"
        aria-label="Период"
      />

      <DatePicker
        v-if="preset === 'custom'"
        v-model="customRange"
        selection-mode="range"
        :manual-input="false"
        placeholder="Диапазон"
        show-icon
      />

      <span class="muted">{{ periodLabel }}</span>
    </div>

    <ErrorState
      v-if="error"
      :error="error"
      @retry="refresh"
    />

    <template v-else>
      <Skeleton
        v-if="!data && pending"
        height="120px"
        border-radius="16px"
      />

      <template v-if="data">
        <AnalyticsKpis :summary="data.summary" />

        <div class="analytics__grid">
          <Card>
            <template #title>
              Выручка по дням
            </template>
            <template #content>
              <RevenueBars :buckets="data.day" />
            </template>
          </Card>

          <CategoryBreakdown :buckets="data.categories" />
        </div>

        <LotsAnalyticsTable
          :lots="data.lots"
          :loading="pending"
          @select="openLot"
        />

        <LotAnalyticsDialog
          :detail="detail"
          @close="closeDetail"
        />
      </template>
    </template>
  </div>
</template>

<style scoped>
.analytics__toolbar {
  align-items: center;
}

.analytics__toolbar :deep(.p-selectbutton) {
  flex-wrap: wrap;
}

.analytics__grid {
  display: grid;
  gap: 16px;
  grid-template-columns: minmax(0, 2fr) minmax(260px, 1fr);
}

@media (max-width: 900px) {
  .analytics__grid {
    grid-template-columns: 1fr;
  }
}
</style>
