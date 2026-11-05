<script setup lang="ts">
import { fetchCategories } from '~/entities/category'
import { useApi } from '~/shared/api'

const api = useApi()
const route = useRoute()
const router = useRouter()

const { data: categories } = await useAsyncData('categories', () => fetchCategories(api))

const category = ref<string | null>(
  typeof route.query.category === 'string' ? route.query.category : null,
)
const search = ref(typeof route.query.q === 'string' ? route.query.q : '')

const apply = () => {
  router.push({
    query: {
      ...route.query,
      category: category.value ?? undefined,
      q: search.value.trim() || undefined,
    },
  })
}
</script>

<template>
  <div class="row filters">
    <Select
      v-model="category"
      :options="categories ?? []"
      option-label="name"
      option-value="id"
      placeholder="Все категории"
      show-clear
      class="filters__select"
      @change="apply"
    />
    <InputText
      v-model="search"
      placeholder="Поиск по названию"
      class="filters__search"
      @keyup.enter="apply"
    />
    <Button
      label="Найти"
      icon="pi pi-search"
      outlined
      @click="apply"
    />
  </div>
</template>

<style scoped>
.filters__select {
  min-width: 220px;
}

.filters__search {
  flex: 1;
}

@media (max-width: 640px) {
  .filters > * {
    width: 100%;
  }
}
</style>
