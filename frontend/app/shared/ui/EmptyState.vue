<script setup lang="ts">
withDefaults(defineProps<{ title: string; description?: string }>(), { description: '' })
</script>

<template>
  <div class="empty-state">
    <i
      class="pi pi-inbox empty-state__icon"
      aria-hidden="true"
    />
    <p class="empty-state__title">
      {{ title }}
    </p>
    <p
      v-if="description"
      class="muted"
    >
      {{ description }}
    </p>
  </div>
</template>

<style scoped>
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 48px 16px;
  text-align: center;
}

.empty-state__icon {
  font-size: 2rem;
  color: var(--p-text-muted-color);
}

.empty-state__title {
  margin: 0;
  font-weight: 600;
}
</style>
