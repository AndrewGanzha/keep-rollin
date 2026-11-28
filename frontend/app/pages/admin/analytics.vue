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
  periodReady,
  periodError,
  currency,
  comparisonRange,
  comparisonLabel,
  comparisonPeriodError,
  comparison,
  comparisonPending,
  comparisonError,
  refreshComparison,
  openLot,
  detail,
  detailLoading,
  detailOffset,
  detailPageSize,
  pageDetail,
  closeDetail,
  downloadCsv,
  exporting,
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
        :invalid="periodError"
        placeholder="Диапазон"
        aria-label="Диапазон отчёта"
        show-icon
      />

      <span class="muted">{{ periodLabel }}</span>

      <Button
        label="Скачать CSV"
        icon="pi pi-download"
        outlined
        :loading="exporting"
        :disabled="!periodReady"
        @click="downloadCsv"
      />
    </div>

    <Message
      v-if="!periodReady"
      severity="warn"
      size="small"
    >
      {{ periodError ? 'Выберите период до 366 дней' : 'Укажите дату окончания периода' }}
    </Message>

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
        <div class="row analytics__toolbar">
          <label for="analytics-comparison">Сравнить с периодом</label>
          <DatePicker
            v-model="comparisonRange"
            input-id="analytics-comparison"
            selection-mode="range"
            :manual-input="false"
            :invalid="comparisonPeriodError"
            placeholder="Диапазон"
            show-icon
            show-clear
          />
          <span
            v-if="comparisonLabel && comparisonPending"
            class="muted"
            role="status"
          >Загружаем сравнение…</span>
        </div>

        <Message
          v-if="comparisonPeriodError"
          severity="warn"
          size="small"
        >
          Выберите период сравнения до 366 дней
        </Message>

        <ErrorState
          v-if="comparisonLabel && comparisonError && !comparisonPending"
          :error="comparisonError"
          @retry="refreshComparison"
        />

        <AnalyticsKpis
          :summary="data.summary"
          :currency="currency"
          :comparison="periodReady && !pending && !comparisonPending && !comparisonError ? comparison : null"
        />

        <div class="analytics__grid">
          <Card>
            <template #title>
              Выручка по дням
            </template>
            <template #content>
              <RevenueBars
                :buckets="data.day"
                :currency="currency"
              />
            </template>
          </Card>

          <CategoryBreakdown
            :buckets="data.categories"
            :currency="currency"
          />
        </div>

        <LotsAnalyticsTable
          :lots="data.lots"
          :currency="currency"
          :loading="pending || (detailLoading && !detail)"
          @select="openLot"
        />

        <LotAnalyticsDialog
          :detail="detail"
          :currency="currency"
          :loading="detailLoading"
          :offset="detailOffset"
          :page-size="detailPageSize"
          @page="pageDetail"
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
  max-width: 100%;
}

.analytics__grid {
  display: grid;
  gap: 16px;
  grid-template-columns: minmax(0, 2fr) minmax(260px, 1fr);
}

@media (max-width: 900px) {
  .analytics__grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
