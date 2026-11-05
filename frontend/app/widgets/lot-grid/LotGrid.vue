<script setup lang="ts">
import type { Characteristic } from '~/entities/category'
import { LotCard, type Lot } from '~/entities/lot'
import { EmptyState } from '~/shared/ui'

const props = withDefaults(
  defineProps<{ lots: Lot[]; loading?: boolean; labels?: Record<string, Characteristic> }>(),
  { loading: false, labels: () => ({}) },
)

const showEmpty = computed(() => !props.loading && props.lots.length === 0)
</script>

<template>
  <div
    v-if="loading"
    class="grid"
  >
    <Skeleton
      v-for="index in 6"
      :key="index"
      height="340px"
      border-radius="16px"
    />
  </div>

  <EmptyState
    v-else-if="showEmpty"
    title="Ничего не найдено"
    description="Попробуйте изменить категорию или поисковый запрос"
  />

  <div
    v-else
    class="grid"
  >
    <LotCard
      v-for="lot in lots"
      :key="lot.id"
      :lot="lot"
      :labels="labels"
    />
  </div>
</template>
