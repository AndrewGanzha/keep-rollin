<script setup lang="ts">
import type { AnalyticsBucket } from '../model/analytics.types'
import { formatMoney } from '~/shared/lib'

const props = defineProps<{ buckets: AnalyticsBucket[] }>()

const max = computed(() => Math.max(...props.buckets.map(bucket => bucket.revenue_minor), 1))
const step = computed(() => Math.max(1, Math.ceil(props.buckets.length / 8)))

const barHeight = (value: number): string => `${Math.round((value / max.value) * 100)}%`
const shortLabel = (key: string): string => key.slice(5)
const tooltip = (bucket: AnalyticsBucket): string =>
  `${bucket.label}: ${formatMoney(bucket.revenue_minor)} · ${bucket.rentals_count} аренд`
</script>

<template>
  <div class="chart">
    <p
      v-if="buckets.every(bucket => bucket.revenue_minor === 0)"
      class="muted chart__empty"
    >
      Нет выручки за период
    </p>

    <div
      v-else
      class="chart__scroll"
    >
      <div
        class="chart__bars"
        role="img"
        :aria-label="`Выручка по дням, ${buckets.length} точек`"
        :style="{ minWidth: `${Math.max(buckets.length * 18, 320)}px` }"
      >
        <div
          v-for="(bucket, index) in buckets"
          :key="bucket.key"
          class="chart__col"
          :title="tooltip(bucket)"
        >
          <div class="chart__bar-area">
            <div
              class="chart__bar"
              :style="{ height: barHeight(bucket.revenue_minor) }"
            />
          </div>
          <span class="chart__label">
            {{ index % step === 0 ? shortLabel(bucket.key) : '' }}
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chart {
  min-height: 180px;
}

.chart__empty {
  margin: 0;
  padding: 48px 0;
  text-align: center;
}

.chart__scroll {
  overflow-x: auto;
}

.chart__bars {
  display: flex;
  align-items: flex-end;
  gap: 4px;
  height: 180px;
}

.chart__col {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 4px;
  height: 100%;
}

.chart__bar-area {
  display: flex;
  flex: 1;
  align-items: flex-end;
  min-height: 0;
}

.chart__bar {
  width: 100%;
  min-height: 2px;
  border-radius: 3px 3px 0 0;
  background: var(--p-primary-color);
}

.chart__label {
  height: 16px;
  color: var(--p-text-muted-color);
  font-size: 0.65rem;
  white-space: nowrap;
}
</style>
