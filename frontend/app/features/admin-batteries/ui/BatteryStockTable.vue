<script setup lang="ts">
import type { BatteryStock } from '~/entities/battery'
import { EmptyState } from '~/shared/ui'

const props = withDefaults(
  defineProps<{
    items: BatteryStock[]
    drafts: Record<string, number>
    saving?: string | null
    loading?: boolean
  }>(),
  { saving: null, loading: false },
)

const emit = defineEmits<{
  'update:draft': [batteryType: string, quantity: number | null]
  save: [item: BatteryStock]
}>()

const draftOf = (item: BatteryStock): number =>
  props.drafts[item.battery_type] ?? item.quantity

const dirty = (item: BatteryStock): boolean => draftOf(item) !== item.quantity
const free = (item: BatteryStock): number => item.quantity - item.peak_committed
</script>

<template>
  <DataTable
    :value="items"
    data-key="battery_type"
    :loading="loading"
    striped-rows
    size="small"
    class="admin-table"
  >
    <template #empty>
      <EmptyState
        title="Остатков нет"
        description="Аккумуляторы ещё не заведены"
      />
    </template>

    <Column
      header="Тип"
      style="min-width: 200px"
    >
      <template #body="{ data }">
        <div class="cell">
          <span>{{ data.name }}</span>
          <span class="muted">{{ data.battery_type }}</span>
        </div>
      </template>
    </Column>

    <Column
      header="Остаток"
      style="min-width: 220px"
    >
      <template #body="{ data }">
        <div class="stock-cell">
          <InputNumber
            :model-value="draftOf(data)"
            :min="0"
            :max="1000"
            :step="1"
            :allow-empty="false"
            size="small"
            input-id="battery-quantity"
            :aria-label="`Остаток ${data.name}`"
            @update:model-value="emit('update:draft', data.battery_type, $event)"
          />
          <Button
            label="Сохранить"
            size="small"
            severity="secondary"
            :disabled="!dirty(data)"
            :loading="saving === data.battery_type"
            @click="emit('save', data)"
          />
        </div>
      </template>
    </Column>

    <Column
      header="Забронировано"
      style="min-width: 140px"
    >
      <template #body="{ data }">
        <span>{{ data.peak_committed }}</span>
      </template>
    </Column>

    <Column
      header="Свободно"
      style="min-width: 140px"
    >
      <template #body="{ data }">
        <Tag
          :value="String(free(data))"
          :severity="free(data) > 0 ? 'success' : 'danger'"
        />
      </template>
    </Column>
  </DataTable>
</template>

<style scoped>
.cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.stock-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.muted {
  color: var(--p-text-muted-color);
  font-size: 0.85rem;
}
</style>
