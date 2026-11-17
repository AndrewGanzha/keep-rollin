<script setup lang="ts">
import type { Category } from '~/entities/category'
import { priceFromLabel, priceFromNote, variantLabel, type Lot, type LotStatus } from '~/entities/lot'
import { EmptyState } from '~/shared/ui'

const props = withDefaults(
  defineProps<{ lots: Lot[]; categories: Category[]; loading?: boolean }>(),
  { loading: false },
)

const emit = defineEmits<{ edit: [lot: Lot]; 'change-status': [lot: Lot] }>()

const severity: Record<LotStatus, 'success' | 'warn' | 'danger' | 'secondary'> = {
  active: 'success',
  maintenance: 'warn',
  overdue: 'danger',
  archived: 'secondary',
}

const statusLabels: Record<LotStatus, string> = {
  active: 'Активен',
  maintenance: 'Обслуживание',
  overdue: 'Просрочен',
  archived: 'Архив',
}

const categoryName = (id: string): string =>
  props.categories.find((item: Category) => item.id === id)?.name ?? id

const statusSeverity = (value: LotStatus) => severity[value]
const statusLabel = (value: LotStatus) => statusLabels[value]
</script>

<template>
  <DataTable
    :value="lots"
    data-key="id"
    :loading="loading"
    striped-rows
    size="small"
    scrollable
    class="admin-table"
  >
    <template #empty>
      <EmptyState
        title="Лотов нет"
        description="Создайте первый лот"
      />
    </template>

    <Column
      header="Лот"
      style="min-width: 200px"
    >
      <template #body="{ data }">
        <div class="cell">
          <span>{{ data.name }}</span>
          <span class="muted">/{{ data.slug }}</span>
        </div>
      </template>
    </Column>

    <Column
      header="Категория"
      style="min-width: 150px"
    >
      <template #body="{ data }">
        {{ categoryName(data.category_id) }}
      </template>
    </Column>

    <Column
      header="Срок"
      style="min-width: 110px"
    >
      <template #body="{ data }">
        {{ data.rental_unit === 'hour' ? 'По часам' : 'Посуточно' }}
      </template>
    </Column>

    <Column
      header="Цена"
      style="min-width: 170px"
    >
      <template #body="{ data }">
        <div class="cell">
          <span>{{ priceFromLabel(data) }}</span>
          <span
            v-if="priceFromNote(data)"
            class="muted"
          >{{ priceFromNote(data) }}</span>
        </div>
      </template>
    </Column>

    <Column
      header="Варианты"
      style="min-width: 120px"
    >
      <template #body="{ data }">
        {{ data.variants.map((variant: { battery_count: number }) => variantLabel(variant.battery_count)).join(' / ') }}
      </template>
    </Column>

    <Column
      header="Статус"
      style="min-width: 130px"
    >
      <template #body="{ data }">
        <Tag
          :severity="statusSeverity(data.status)"
          :value="statusLabel(data.status)"
        />
      </template>
    </Column>

    <Column
      header="Действия"
      style="min-width: 200px"
    >
      <template #body="{ data }">
        <div class="row actions">
          <Button
            label="Изменить"
            size="small"
            outlined
            @click="emit('edit', data)"
          />
          <Button
            label="Статус"
            size="small"
            text
            @click="emit('change-status', data)"
          />
        </div>
      </template>
    </Column>
  </DataTable>
</template>

<style scoped>
.admin-table :deep(.p-tag) {
  white-space: nowrap;
}

.admin-table :deep(.p-datatable-table) {
  min-width: 920px;
}

.cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.actions {
  flex-wrap: wrap;
  gap: 4px;
}
</style>
