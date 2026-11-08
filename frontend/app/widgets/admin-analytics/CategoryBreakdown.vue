<script setup lang="ts">
import type { AnalyticsBucket } from '~/entities/analytics'
import { formatMoney } from '~/shared/lib'

const props = defineProps<{ buckets: AnalyticsBucket[] }>()

const total = computed(() =>
  props.buckets.reduce((sum, bucket) => sum + bucket.revenue_minor, 0),
)

const share = (bucket: AnalyticsBucket): number =>
  total.value > 0 ? (bucket.revenue_minor / total.value) * 100 : 0
</script>

<template>
  <Card>
    <template #title>
      Выручка по категориям
    </template>

    <template #content>
      <p
        v-if="buckets.length === 0 || total === 0"
        class="muted"
        style="margin: 0"
      >
        Нет данных за период
      </p>

      <div
        v-else
        class="stack"
        style="gap: 12px"
      >
        <div
          v-for="bucket in buckets"
          :key="bucket.key"
          class="category"
        >
          <div class="category__head">
            <span>{{ bucket.label }}</span>
            <strong>{{ formatMoney(bucket.revenue_minor) }}</strong>
          </div>
          <div class="category__bar">
            <div
              class="category__fill"
              :style="{ width: `${share(bucket)}%` }"
            />
          </div>
          <span class="muted category__meta">
            {{ bucket.rentals_count }} аренд · {{ share(bucket).toFixed(1) }}%
          </span>
        </div>
      </div>
    </template>
  </Card>
</template>

<style scoped>
.category {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.category__head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  font-size: 0.9rem;
}

.category__bar {
  height: 8px;
  border-radius: 4px;
  background: var(--p-content-border-color);
  overflow: hidden;
}

.category__fill {
  height: 100%;
  border-radius: 4px;
  background: var(--p-primary-color);
}

.category__meta {
  font-size: 0.75rem;
}
</style>
