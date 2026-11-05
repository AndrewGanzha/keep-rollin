<script setup lang="ts">
import type { Characteristic } from '~/entities/category'
import type { Lot } from '../model/lot.types'
import { formatMoney } from '~/shared/lib'

const props = defineProps<{ lot: Lot; labels?: Record<string, Characteristic> }>()

const features = computed(() =>
  Object.entries(props.lot.characteristics)
    .slice(0, 3)
    .map(([code, value]) => {
      const characteristic = props.labels?.[code]

      if (!characteristic) {
        return `${code}: ${value}`
      }

      return `${characteristic.name}: ${value}${characteristic.unit ? ` ${characteristic.unit}` : ''}`
    }),
)
</script>

<template>
  <Card class="lot-card">
    <template #header>
      <div class="lot-card__media">
        <i
          class="pi pi-bolt"
          aria-hidden="true"
        />
      </div>
    </template>

    <template #title>
      <NuxtLink
        :to="`/lots/${lot.slug}`"
        class="lot-card__title"
      >{{ lot.name }}</NuxtLink>
    </template>

    <template #content>
      <div
        class="stack"
        style="gap: 10px"
      >
        <Tag
          v-if="lot.status !== 'active'"
          severity="warn"
          :value="lot.status"
        />
        <ul class="lot-card__features">
          <li
            v-for="feature in features"
            :key="feature"
          >
            {{ feature }}
          </li>
        </ul>
      </div>
    </template>

    <template #footer>
      <div
        class="row"
        style="justify-content: space-between"
      >
        <span class="lot-card__price">{{ formatMoney(lot.price_minor, lot.currency) }}</span>
        <NuxtLink :to="`/lots/${lot.slug}`">
          <Button
            label="Подробнее"
            size="small"
            outlined
          />
        </NuxtLink>
      </div>
    </template>
  </Card>
</template>

<style scoped>
.lot-card {
  height: 100%;
}

.lot-card__media {
  display: flex;
  height: 148px;
  align-items: center;
  justify-content: center;
  border-radius: var(--p-content-border-radius) var(--p-content-border-radius) 0 0;
  background: linear-gradient(135deg, var(--p-primary-100), var(--p-primary-300));
}

.lot-card__media i {
  font-size: 3rem;
  color: var(--p-primary-700);
}

.lot-card__title {
  color: var(--p-text-color);
  text-decoration: none;
  font-size: 1.1rem;
}

.lot-card__features {
  margin: 0;
  padding-left: 18px;
  color: var(--p-text-muted-color);
  font-size: 0.9rem;
}

.lot-card__price {
  font-weight: 700;
}
</style>
