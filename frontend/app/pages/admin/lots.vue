<script setup lang="ts">
import type { CreateLotRequest, Lot, LotStatus, LotStatusRequest } from '~/entities/lot'
import { useAdminLots } from '~/features/admin-lots'
import { ErrorState, PageHeading } from '~/shared/ui'
import { AdminLotsTable, LotFormDialog, LotStatusDialog } from '~/widgets/admin-lots'

definePageMeta({ layout: 'admin', middleware: ['auth', 'role'] })

useHead({ title: 'Лоты — админка' })

const {
  data,
  categories,
  pending,
  error,
  refresh,
  status,
  creating,
  create,
  updating,
  updateStatus,
} = await useAdminLots()
const dialogOpen = ref(false)
const statusTarget = ref<Lot | null>(null)

const statusOptions: { label: string; value: LotStatus }[] = [
  { label: 'Активен', value: 'active' },
  { label: 'Обслуживание', value: 'maintenance' },
  { label: 'Просрочен', value: 'overdue' },
  { label: 'Архив', value: 'archived' },
]

const onCreate = async (payload: CreateLotRequest) => {
  const lot = await create(payload)

  if (lot) {
    dialogOpen.value = false
  }
}

const onStatus = async (lot: Lot, next: LotStatusRequest['status']) => {
  if (await updateStatus(lot, next)) {
    statusTarget.value = null
  }
}
</script>

<template>
  <div class="stack">
    <PageHeading
      title="Лоты"
      subtitle="Каталог: добавление и статусы"
    />

    <div class="row">
      <Button
        label="Добавить лот"
        icon="pi pi-plus"
        @click="dialogOpen = true"
      />
      <Select
        v-model="status"
        :options="statusOptions"
        option-label="label"
        option-value="value"
        placeholder="Все статусы"
        show-clear
      />
    </div>

    <ErrorState
      v-if="error"
      :error="error"
      @retry="refresh"
    />

    <template v-else>
      <AdminLotsTable
        :lots="data?.items ?? []"
        :categories="categories ?? []"
        :loading="pending"
        @change-status="statusTarget = $event"
      />

      <LotStatusDialog
        :lot="statusTarget"
        :pending="updating"
        @update:lot="statusTarget = $event"
        @confirm="onStatus"
      />

      <LotFormDialog
        v-model:visible="dialogOpen"
        :categories="categories ?? []"
        :pending="creating"
        @submit="onCreate"
      />
    </template>
  </div>
</template>
