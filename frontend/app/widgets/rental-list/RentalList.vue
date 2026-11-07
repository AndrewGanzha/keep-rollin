<script setup lang="ts">
import { RentalCard, type Rental } from '~/entities/rental'
import { useTenant } from '~/entities/tenant'
import { EmptyState } from '~/shared/ui'

const props = withDefaults(defineProps<{ rentals: Rental[]; loading?: boolean; pendingId?: string | null }>(), {
  loading: false,
  pendingId: null,
})

const emit = defineEmits<{ cancel: [id: string]; report: [id: string] }>()

const tenant = useTenant()
const timeZone = computed(() => tenant.value?.timezone)

type RentalTab = 'all' | 'current' | 'completed' | 'cancelled'

const activeTab = ref<RentalTab>('current')

const groups: { key: RentalTab; label: string; emptyTitle: string; emptyDescription: string }[] = [
  {
    key: 'current',
    label: 'Актуальные',
    emptyTitle: 'Актуальных аренд нет',
    emptyDescription: 'Забронированные, активные и просроченные аренды появятся здесь',
  },
  {
    key: 'completed',
    label: 'Завершённые',
    emptyTitle: 'Завершённых аренд нет',
    emptyDescription: 'История завершённых поездок появится здесь',
  },
  {
    key: 'cancelled',
    label: 'Отменённые',
    emptyTitle: 'Отменённых аренд нет',
    emptyDescription: 'Отменённые брони появятся здесь',
  },
  {
    key: 'all',
    label: 'Все',
    emptyTitle: 'Аренд пока нет',
    emptyDescription: 'Выберите лот в каталоге и забронируйте удобный интервал',
  },
]

const currentStatuses: Rental['status'][] = ['booked', 'active', 'overdue']

const countOf = (key: RentalTab): number => {
  if (key === 'all') {
    return props.rentals.length
  }
  if (key === 'current') {
    return props.rentals.filter(rental => currentStatuses.includes(rental.status)).length
  }
  return props.rentals.filter(rental => rental.status === key).length
}

const rentalsOf = (key: RentalTab): Rental[] => {
  if (key === 'all') {
    return props.rentals
  }
  if (key === 'current') {
    return props.rentals.filter(rental => currentStatuses.includes(rental.status))
  }
  return props.rentals.filter(rental => rental.status === key)
}
</script>

<template>
  <div
    v-if="loading"
    class="stack"
  >
    <Skeleton
      v-for="index in 2"
      :key="index"
      height="180px"
      border-radius="16px"
    />
  </div>

  <Tabs
    v-else
    v-model:value="activeTab"
  >
    <TabList>
      <Tab
        v-for="group in groups"
        :key="group.key"
        :value="group.key"
      >
        {{ group.label }} ({{ countOf(group.key) }})
      </Tab>
    </TabList>
    <TabPanels>
      <TabPanel
        v-for="group in groups"
        :key="group.key"
        :value="group.key"
      >
        <EmptyState
          v-if="rentalsOf(group.key).length === 0"
          :title="group.emptyTitle"
          :description="group.emptyDescription"
        />
        <div
          v-else
          class="stack"
        >
          <RentalCard
            v-for="rental in rentalsOf(group.key)"
            :key="rental.id"
            :rental="rental"
            :time-zone="timeZone"
            @cancel="emit('cancel', $event)"
            @report="emit('report', $event)"
          />
        </div>
      </TabPanel>
    </TabPanels>
  </Tabs>
</template>
