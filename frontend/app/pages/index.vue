<script setup lang="ts">
import { useLots } from '~/features/catalog/browse'
import { CatalogFilters } from '~/features/catalog/filter'
import { ErrorState, PageHeading } from '~/shared/ui'
import { LotGrid } from '~/widgets/lot-grid'

const { data, pending, error, labels, refresh } = await useLots()
</script>

<template>
  <div class="stack">
    <PageHeading
      title="Каталог"
      subtitle="Электробайки и аккумуляторы в аренду — бронируйте на удобный интервал"
    />

    <CatalogFilters />

    <ErrorState
      v-if="error"
      :error="error"
      @retry="refresh"
    />
    <LotGrid
      v-else
      :lots="data?.items ?? []"
      :labels="labels"
      :loading="pending"
    />
  </div>
</template>
