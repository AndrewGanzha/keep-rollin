<script setup lang="ts">
import type { Characteristic } from '~/entities/category'
import { priceFromLabel, priceFromNote, type Availability, type Lot } from '~/entities/lot'
import { useTenant } from '~/entities/tenant'
import { formatDateTime } from '~/shared/lib'
import { EmptyState } from '~/shared/ui'

const props = withDefaults(
  defineProps<{ lot: Lot; availability?: Availability | null; labels?: Record<string, Characteristic> }>(),
  { availability: null, labels: () => ({}) },
)
const emit = defineEmits<{ book: [] }>()

const tenant = useTenant()
const timeZone = computed(() => tenant.value?.timezone)

const price = computed(() => priceFromLabel(props.lot))
const priceNote = computed(() => priceFromNote(props.lot))
const durationHint = computed(() => {
  const minUnits = props.lot.allowed_durations[0] ?? 1

  if (props.lot.rental_unit === 'hour') {
    return `Аренда от ${minUnits} ${minUnits === 1 ? 'часа' : 'часов'}`
  }

  return `Аренда от ${minUnits} ${minUnits === 1 ? 'дня' : 'суток'}`
})

const characteristics = computed(() =>
  Object.entries(props.lot.characteristics).map(([code, value]) => {
    const characteristic = props.labels[code]

    return {
      code,
      name: characteristic?.name ?? code,
      unit: characteristic?.unit ?? '',
      value,
    }
  }),
)

const busy = computed(() => props.availability?.busy ?? [])
</script>

<template>
  <article class="stack lot">
    <div class="lot__media">
      <i
        class="pi pi-bolt"
        aria-hidden="true"
      />
    </div>

    <div
      class="row"
      style="justify-content: space-between; align-items: flex-start"
    >
      <div
        class="stack"
        style="gap: 6px"
      >
        <h1 class="section-title">
          {{ lot.name }}
        </h1>
        <p
          class="muted"
          style="margin: 0"
        >
          {{ lot.description }}
        </p>
      </div>
      <div
        class="stack"
        style="gap: 8px; align-items: flex-end"
      >
        <span class="lot__price">{{ price }}</span>
        <small
          v-if="priceNote"
          class="muted lot__note"
        >
          {{ priceNote }}
        </small>
      </div>
    </div>

    <Card>
      <template #title>
        Характеристики
      </template>
      <template #content>
        <dl class="lot__specs">
          <template
            v-for="item in characteristics"
            :key="item.code"
          >
            <dt>{{ item.name }}</dt>
            <dd>{{ item.value }}{{ item.unit ? ` ${item.unit}` : '' }}</dd>
          </template>
        </dl>
      </template>
    </Card>

    <Card>
      <template #title>
        Занятость
      </template>
      <template #content>
        <p
          v-if="busy.length === 0"
          class="muted"
          style="margin: 0"
        >
          Свободен ближайшие две недели
        </p>
        <ul
          v-else
          class="lot__busy"
        >
          <li
            v-for="interval in busy"
            :key="interval.start"
          >
            {{ formatDateTime(interval.start, timeZone) }} — {{ formatDateTime(interval.end, timeZone) }}
          </li>
        </ul>
      </template>
    </Card>

    <Button
      v-if="lot.is_bookable && lot.variants.length > 0"
      label="Забронировать"
      size="large"
      @click="emit('book')"
    />
    <small
      v-if="lot.is_bookable && lot.variants.length > 0"
      class="muted"
    >
      {{ durationHint }}. Точную цену покажет расчёт при выборе варианта.
    </small>
    <EmptyState
      v-else-if="lot.variants.length === 0"
      title="Цена не задана"
      description="Владелец ещё не настроил тарифы для этого лота"
    />
    <Message
      v-else
      severity="warn"
      :closable="false"
    >
      Лот недоступен для брони ({{ lot.status }})
    </Message>
  </article>
</template>

<style scoped>
.lot__media {
  display: flex;
  height: 280px;
  align-items: center;
  justify-content: center;
  border-radius: var(--p-content-border-radius);
  background: linear-gradient(135deg, var(--p-primary-100), var(--p-primary-300));
}

.lot__media i {
  font-size: 5rem;
  color: var(--p-primary-700);
}

.lot__price {
  font-size: 1.5rem;
  font-weight: 700;
}

.lot__specs {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 8px 16px;
  margin: 0;
}

.lot__specs dt {
  color: var(--p-text-muted-color);
}

.lot__specs dd {
  margin: 0;
  font-weight: 600;
}

.lot__busy {
  margin: 0;
  padding-left: 18px;
}
</style>
