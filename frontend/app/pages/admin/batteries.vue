<script setup lang="ts">
import { useAdminBatteries } from '~/features/admin-batteries'
import { BatteryStockTable } from '~/features/admin-batteries'
import { ErrorState, PageHeading } from '~/shared/ui'

definePageMeta({ layout: 'admin', middleware: ['auth', 'role', 'owner'] })

useHead({ title: 'Аккумуляторы — админка' })

const { data, pending, error, refresh, drafts, saving, setDraft, save } = await useAdminBatteries()
</script>

<template>
  <div class="stack">
    <PageHeading
      title="Аккумуляторы"
      subtitle="Пул АКБ по типам: остаток, занятость и свободный запас"
    />

    <ErrorState
      v-if="error"
      :error="error"
      @retry="refresh"
    />

    <template v-else>
      <BatteryStockTable
        :items="data ?? []"
        :drafts="drafts"
        :saving="saving"
        :loading="pending"
        @update:draft="setDraft"
        @save="save"
      />

      <p class="muted hint">
        «Забронировано» — пик одновременной занятости по броням и активным арендам.
        Уменьшить остаток ниже этого пика нельзя.
      </p>
    </template>
  </div>
</template>

<style scoped>
.hint {
  margin: 0;
  font-size: 0.85rem;
}

.muted {
  color: var(--p-text-muted-color);
}
</style>
